package verification

import (
	"fmt"
	"log"
	"math/rand"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type VerificationService struct {
	Config *config.Config
}

func NewVerificationService(cfg *config.Config) *VerificationService {
	// Initialize random seed
	rand.Seed(time.Now().UnixNano())
	return &VerificationService{Config: cfg}
}

func (v *VerificationService) HandleButtonClick(s *discordgo.Session, i *discordgo.InteractionCreate) {
	customID := i.MessageComponentData().CustomID

	if strings.HasPrefix(customID, "verif_approve:") {
		userID := strings.TrimPrefix(customID, "verif_approve:")
		v.HandleApprove(s, i, userID)
		return
	}
	if strings.HasPrefix(customID, "verif_warn:") {
		userID := strings.TrimPrefix(customID, "verif_warn:")
		v.HandleWarn(s, i, userID)
		return
	}
	if strings.HasPrefix(customID, "verif_kick:") {
		userID := strings.TrimPrefix(customID, "verif_kick:")
		v.HandleKick(s, i, userID)
		return
	}

	switch customID {
	case "verify_button":
		// Reserved for future use
	case "sso_verify_button":
		// Removed SSO integration
	}
}

func (v *VerificationService) HandleVerifyCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	options := i.ApplicationCommandData().Options
	if len(options) == 0 {
		return
	}
	subcommand := options[0].Name

	switch subcommand {
	case "bypass":
		if (i.Member.Permissions & discordgo.PermissionKickMembers) == 0 {
			content := "❌ Nemáš oprávnění pro bypass verifikace."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
				Content: &content,
			})
			return
		}

		targetUser := options[0].Options[0].UserValue(s)
		v.HandleApprove(s, i, targetUser.ID)

	case "set_bypass":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Nemáš oprávnění pro nastavení bypass hesla."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
				Content: &content,
			})
			return
		}
		newPassword := options[0].Options[0].StringValue()
		if redis_client.Client != nil {
			redis_client.Client.Set(redis_client.Ctx, "verify:bypass_hash", newPassword, 0)
		}
		content := "✅ Heslo nastaveno."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})

	case "ping":
		otp := v.GenerateOTP()
		v.sendDM(s, i.Member.User.ID, otp)
		content := "✅ Testovací DM odesláno."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})

	}
}

func (v *VerificationService) GenerateOTP() string {
	const charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
	b := make([]byte, 6)
	for i := range b {
		b[i] = charset[rand.Intn(len(charset))]
	}
	return string(b)
}

func (v *VerificationService) OnMemberJoin(s *discordgo.Session, m *discordgo.GuildMemberAdd) {
	log.Printf("DEBUG: OnMemberJoin triggered for user %s (%s)", m.User.Username, m.User.ID)
	if m.User.Bot {
		return
	}

	// 1. Setup Lock to prevent duplicate handling across multiple bot instances
	lockKey := fmt.Sprintf("verify:dm_lock:%s", m.User.ID)
	if redis_client.Client != nil {
		locked, _ := redis_client.Client.SetNX(redis_client.Ctx, lockKey, "1", 30*time.Second).Result()
		if !locked {
			log.Printf("DEBUG: Another instance is already handling join for user %s", m.User.ID)
			return
		}
	}

	// 2. Initial setup - add waiting role
	if v.Config.WaitingRoleID != "" {
		s.GuildMemberRoleAdd(m.GuildID, m.User.ID, v.Config.WaitingRoleID)
	}

	// 3. Setup state in Redis
	otp := v.GenerateOTP()
	key := fmt.Sprintf("verify:state:%s", m.User.ID)
	
	if redis_client.Client != nil {
		redis_client.Client.HSet(redis_client.Ctx, key, map[string]interface{}{
			"otp":        otp,
			"status":     "PENDING",
			"created_at": time.Now().Unix(),
			"attempts":   0,
		})
	}

	// 4. Send DM
	v.sendDM(s, m.User.ID, otp)

	// 5. Log join in mod channel (čakárna-log)
	v.logJoin(s, m)
}

func (v *VerificationService) sendDM(s *discordgo.Session, userID string, otp string) {
	channel, err := s.UserChannelCreate(userID)
	if err != nil {
		log.Printf("Error creating DM channel for %s: %v", userID, err)
		return
	}

	msg := fmt.Sprintf("**🔒 Ověření účtu**\n\nAhoj! Vítej na serveru.\nPro dokončení ověření prosím pošli sem do chatu tento kód:\n\n> **`%s`**", otp)
	s.ChannelMessageSend(channel.ID, msg)
}

func (v *VerificationService) logJoin(s *discordgo.Session, m *discordgo.GuildMemberAdd) {
	logChannel := v.Config.VerificationChannel
	verifLogChannel := v.Config.VerifLogChannel
	if logChannel == "" {
		return
	}

	creationTime := v.getCreationTime(m.User.ID)
	
	msgContent := fmt.Sprintf("**Nový uživatel se připojil na server!**\n\n"+
		"**Uživatel:** %s (%s)\n"+
		"**ID:** %s\n"+
		"**Účet vytvořen:** <t:%d:F> (<t:%d:R>)\n"+
		"**Avatar:** [Odkaz](%s)\n"+
		"**Bio:** _Bio není dostupné_\n\n"+
		"Automaticky mu byla přidělena ověřovací role.\n\n"+
		"⏳ **Status:** Čeká na zadání kódu...",
		m.User.Mention(), m.User.Username, m.User.ID, creationTime, creationTime, m.User.AvatarURL("1024"))

	log.Printf("DEBUG: Sending join log to channel %s", logChannel)
	msg, err := s.ChannelMessageSend(logChannel, msgContent)
	if err != nil {
		log.Printf("Error sending join log to channel %s: %v", logChannel, err)
		return
	}

	// Also send to Verification Log channel if configured
	if verifLogChannel != "" && verifLogChannel != logChannel {
		s.ChannelMessageSend(verifLogChannel, msgContent)
	}

	key := fmt.Sprintf("verify:state:%s", m.User.ID)
	if redis_client.Client != nil {
		redis_client.Client.HSet(redis_client.Ctx, key, "approve_msg_id", msg.ID)
	}
}

func (v *VerificationService) OnMessageCreate(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID != "" {
		return
	}

	uid := m.Author.ID
	key := fmt.Sprintf("verify:state:%s", uid)

	if redis_client.Client == nil {
		return
	}

	state, err := redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
	if err != nil || len(state) == 0 {
		return
	}

	if state["status"] == "APPROVED" {
		return
	}

	userInput := strings.TrimSpace(m.Content)
	otp := state["otp"]
	globalCode := v.Config.VerificationCode

	if redis_client.Client != nil {
		bypassHash, _ := redis_client.Client.Get(redis_client.Ctx, "verify:bypass_hash").Result()
		if bypassHash != "" && userInput == bypassHash {
			v.HandleApprove(s, &discordgo.InteractionCreate{
				Interaction: &discordgo.Interaction{
					GuildID: m.GuildID,
					Member:  m.Member,
				},
			}, uid)
			s.ChannelMessageSend(m.ChannelID, "✅ **Tajné heslo přijato.** Vstup povolen.")
			return
		}
	}

	if userInput == otp || (globalCode != "" && strings.EqualFold(userInput, globalCode)) {
		if redis_client.Client != nil {
			redis_client.Client.HSet(redis_client.Ctx, key, "status", "WAITING_FOR_APPROVAL")
			redis_client.Client.HSet(redis_client.Ctx, key, "code_entered_at", time.Now().Unix())
		}

		s.ChannelMessageSend(m.ChannelID, "✅ **Kód je správný.** Nyní prosím čekej, než moderátor potvrdí tvůj přístup.")
		v.notifyMods(s, uid)
	} else {
		if redis_client.Client != nil {
			redis_client.Client.HIncrBy(redis_client.Ctx, key, "attempts", 1)
		}
		s.ChannelMessageSend(m.ChannelID, "❌ **Špatný kód.** Zkus to znovu.")
	}
}

func (v *VerificationService) notifyMods(s *discordgo.Session, userID string) {
	logChannel := v.Config.VerificationChannel
	if logChannel == "" {
		return
	}
	key := fmt.Sprintf("verify:state:%s", userID)
	msgID := ""
	if redis_client.Client != nil {
		msgID, _ = redis_client.Client.HGet(redis_client.Ctx, key, "approve_msg_id").Result()
	}

	if msgID != "" {
		log.Printf("DEBUG: Notifying mods for user %s, editing message %s", userID, msgID)
		btnApprove := discordgo.Button{
			Label:    "Schválit (Approve)",
			Style:    discordgo.SuccessButton,
			CustomID: "verif_approve:" + userID,
			Emoji:    &discordgo.ComponentEmoji{Name: "✅"},
		}
		btnWarn := discordgo.Button{
			Label:    "Upozornit",
			Style:    discordgo.SecondaryButton,
			CustomID: "verif_warn:" + userID,
			Emoji:    &discordgo.ComponentEmoji{Name: "⚠️"},
		}
		btnKick := discordgo.Button{
			Label:    "Vyhodit (Kick)",
			Style:    discordgo.DangerButton,
			CustomID: "verif_kick:" + userID,
			Emoji:    &discordgo.ComponentEmoji{Name: "🚪"},
		}

		comps := []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btnApprove, btnWarn, btnKick},
			},
		}

		// Update the status in the text message
		msg, err := s.ChannelMessage(logChannel, msgID)
		if err != nil {
			log.Printf("ERROR: Failed to fetch join log message %s: %v", msgID, err)
			return
		}

		newContent := msg.Content
		if strings.Contains(newContent, "Status") {
			newContent = strings.ReplaceAll(newContent, "⏳ **Status:** Čeká na zadání kódu...", "✅ **Status:** Kód zadán. Čeká na schválení.")
		} else {
			newContent += "\n\n✅ **Status:** Kód zadán. Čeká na schválení."
		}

		_, err = s.ChannelMessageEditComplex(&discordgo.MessageEdit{
			ID:         msgID,
			Channel:    logChannel,
			Content:    &newContent,
			Components: &comps,
		})
		if err != nil {
			log.Printf("ERROR: Failed to edit join log message %s: %v", msgID, err)
		} else {
			log.Printf("DEBUG: Successfully updated moderator buttons for user %s", userID)
		}
	} else {
		log.Printf("WARN: No join log message ID found in Redis for user %s", userID)
	}
}

func (v *VerificationService) HandleApprove(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	// 1. Manage roles - Remove waiting role only (as clarified: "verified není jen se odebere role")
	if v.Config.WaitingRoleID != "" {
		s.GuildMemberRoleRemove(i.GuildID, userID, v.Config.WaitingRoleID)
	}

	// 2. Send Greeting to Welcome Channel
	if v.Config.WelcomeChannel != "" {
		greeting := fmt.Sprintf("Nový člen se k nám připojil! Všichni přivítejme <@%s>! Nezapomeň se podívat do 📗pravidla a ℹ️úvod Můžeš se představit v 👋představ-se", userID)
		s.ChannelMessageSend(v.Config.WelcomeChannel, greeting)
	}

	key := fmt.Sprintf("verify:state:%s", userID)
	var state map[string]string
	now := time.Now()
	if redis_client.Client != nil {
		state, _ = redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
		redis_client.Client.HSet(redis_client.Ctx, key, "status", "APPROVED")
		redis_client.Client.HSet(redis_client.Ctx, key, "approved_at", now.Unix())
	}

	v.confirmSuccess(s, userID)

	// Fetch detailed user info
	u, _ := s.User(userID)
	username := userID
	avatar := ""
	if u != nil {
		username = u.Username
		avatar = u.AvatarURL("")
	}
	creationTime := v.getCreationTime(userID)
	accountAge := time.Since(time.Unix(creationTime, 0))
	ageStr := fmt.Sprintf("%d dnech", int(accountAge.Hours()/24))
	if accountAge.Hours() > 24*365 {
		ageStr = fmt.Sprintf("%.1f letech", accountAge.Hours()/(24*365))
	}

	logContent := fmt.Sprintf("✅ **Uživatel ověřen:**\n\n"+
		"**Uživatel:** <@%s> (%s)\n"+
		"**ID:** %s\n"+
		"**Účet vytvořen:** <t:%d:F> (<t:%d:R>)\n"+
		"**Věk účtu:** %s\n"+
		"**Avatar:** %s\n\n"+
		"Automaticky mu byla přidělena ověřovací role.\n\n"+
		"**Časový průběh:**\n"+
		"• Připojení: <t:%d:F>\n"+
		"• Zadání kódu: <t:%d:F>\n"+
		"• Schválení: <t:%d:F>\n\n"+
		"**Moderátor:** Schválil <@%s>",
		userID, username, userID, creationTime, creationTime, ageStr, avatar,
		v.parseInt(state["created_at"]),
		v.parseInt(state["code_entered_at"]),
		now.Unix(),
		i.Member.User.ID)

	s.ChannelMessageSend(v.Config.VerifLogChannel, logContent)

	content := fmt.Sprintf("✅ **Uživatel <@%s> byl schválen moderátorem <@%s>.**", userID, i.Member.User.ID)

	if i.Type == discordgo.InteractionMessageComponent {
		// Try to keep the embed if we can access it
		msg, err := s.ChannelMessage(v.Config.VerificationChannel, i.Message.ID)
		if err == nil && len(msg.Embeds) > 0 {
			embed := msg.Embeds[0]
			embed.Description = fmt.Sprintf("Automaticky mu byla přidělena ověřovací role.\n\n✅ **Status:** Schváleno moderátorem <@%s>", i.Member.User.ID)
			embed.Color = 0x2ecc71 // Success Green
			
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseUpdateMessage,
				Data: &discordgo.InteractionResponseData{
					Embeds:     []*discordgo.MessageEmbed{embed},
					Components: []discordgo.MessageComponent{},
				},
			})
		} else {
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseUpdateMessage,
				Data: &discordgo.InteractionResponseData{
					Content:    content,
					Components: []discordgo.MessageComponent{},
				},
			})
		}
	} else {
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
	}
}

func (v *VerificationService) HandleWarn(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	content := fmt.Sprintf("⚠️ **Varování pro <@%s> bylo zaznamenáno moderátorem <@%s>.**", userID, i.Member.User.ID)
	// For now just respond, we can add more logic later
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: content,
			Flags:   64,
		},
	})
}

func (v *VerificationService) HandleKick(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	err := s.GuildMemberDeleteWithReason(i.GuildID, userID, fmt.Sprintf("Verification rejected by %s", i.Member.User.Username))
	content := ""
	if err != nil {
		content = fmt.Sprintf("❌ Nepodařilo se vyhodit uživatele: %v", err)
	} else {
		content = fmt.Sprintf("🚪 **Uživatel <@%s> byl vyhozen moderátorem <@%s>.**", userID, i.Member.User.ID)
	}
	
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Content:    content,
			Components: []discordgo.MessageComponent{},
		},
	})
}

func (v *VerificationService) getCreationTime(idStr string) int64 {
	var id int64
	fmt.Sscanf(idStr, "%d", &id)
	return (id >> 22) / 1000 + 1420070400
}

func (v *VerificationService) parseInt(s string) int64 {
	var val int64
	fmt.Sscanf(s, "%d", &val)
	return val
}


func (v *VerificationService) confirmSuccess(s *discordgo.Session, userID string) {
	channel, err := s.UserChannelCreate(userID)
	if err == nil {
		s.ChannelMessageSend(channel.ID, "✅ **Ověření úspěšné!** Vítej na serveru.")
	}
}
