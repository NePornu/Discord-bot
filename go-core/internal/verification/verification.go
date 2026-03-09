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
		redis_client.Client.Set(redis_client.Ctx, "verify:bypass_hash", newPassword, 0)
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
	if m.User.Bot {
		return
	}

	// 1. Add unverified role
	if v.Config.VerifiedRole != "" {
		err := s.GuildMemberRoleAdd(m.GuildID, m.User.ID, v.Config.VerifiedRole)
		if err != nil {
			log.Printf("Error adding initial role to %s: %v", m.User.ID, err)
		}
	}

	// 2. Setup state in Redis
	otp := v.GenerateOTP()
	key := fmt.Sprintf("verify:state:%s", m.User.ID)
	redis_client.Client.HSet(redis_client.Ctx, key, map[string]interface{}{
		"otp":        otp,
		"status":     "PENDING",
		"created_at": time.Now().Unix(),
		"attempts":   0,
	})

	// 3. Send DM
	v.sendDM(s, m.User.ID, otp)

	// 4. Log join in mod channel
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
	if v.Config.VerificationChannel == "" {
		return
	}

	creationTime := v.getCreationTime(m.User.ID)
	
	embed := &discordgo.MessageEmbed{
		Title: "Nový uživatel se připojil na server!",
		Color: 0x3498db,
		Thumbnail: &discordgo.MessageEmbedThumbnail{
			URL: m.User.AvatarURL(""),
		},
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Uživatel", Value: fmt.Sprintf("%s (%s)", m.User.Mention(), m.User.Username), Inline: false},
			{Name: "ID", Value: m.User.ID, Inline: true},
			{Name: "Účet vytvořen", Value: fmt.Sprintf("<t:%d:F> (<t:%d:R>)", creationTime, creationTime), Inline: false},
			{Name: "Avatar", Value: fmt.Sprintf("[Odkaz](%s)", m.User.AvatarURL("")), Inline: true},
			{Name: "Bio", Value: "_Bio není dostupné_", Inline: true},
		},
		Description: "Automaticky mu byla přidělena ověřovací role.\n\n⏳ **Status:** Čeká na zadání kódu...",
	}

	msg, err := s.ChannelMessageSendEmbed(v.Config.VerificationChannel, embed)
	if err == nil {
		key := fmt.Sprintf("verify:state:%s", m.User.ID)
		redis_client.Client.HSet(redis_client.Ctx, key, "approve_msg_id", msg.ID)
	}

	// Also send a simple log to the log channel
	if v.Config.VerifLogChannel != "" {
		s.ChannelMessageSend(v.Config.VerifLogChannel, fmt.Sprintf("📥 **Nový uživatel:** %s (%s) se připojil a čeká na ověření.", m.User.Mention(), m.User.ID))
	}
}

func (v *VerificationService) OnMessageCreate(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID != "" {
		return
	}

	uid := m.Author.ID
	key := fmt.Sprintf("verify:state:%s", uid)

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

	if userInput == otp || (globalCode != "" && strings.EqualFold(userInput, globalCode)) {
		redis_client.Client.HSet(redis_client.Ctx, key, "status", "WAITING_FOR_APPROVAL")
		redis_client.Client.HSet(redis_client.Ctx, key, "code_entered_at", time.Now().Unix())

		s.ChannelMessageSend(m.ChannelID, "✅ **Kód je správný.** Nyní prosím čekej, než moderátor potvrdí tvůj přístup.")
		v.notifyMods(s, uid)
	} else {
		redis_client.Client.HIncrBy(redis_client.Ctx, key, "attempts", 1)
		s.ChannelMessageSend(m.ChannelID, "❌ **Špatný kód.** Zkus to znovu.")
	}
}

func (v *VerificationService) notifyMods(s *discordgo.Session, userID string) {
	key := fmt.Sprintf("verify:state:%s", userID)
	msgID, _ := redis_client.Client.HGet(redis_client.Ctx, key, "approve_msg_id").Result()

	if msgID != "" && v.Config.VerificationChannel != "" {
		btnApprove := discordgo.Button{
			Label:    "Schválit (Approve)",
			Style:    discordgo.SuccessButton,
			CustomID: "verif_approve:" + userID,
			Emoji:    &discordgo.ComponentEmoji{Name: "✅"},
		}
		btnWarn := discordgo.Button{
			Label:    "Upozornit",
			Style:    discordgo.SecondaryButton, // Gray/Secondary
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

		// Update the embed status
		msg, err := s.ChannelMessage(v.Config.VerificationChannel, msgID)
		if err == nil && len(msg.Embeds) > 0 {
			embed := msg.Embeds[0]
			embed.Description = "Automaticky mu byla přidělena ověřovací role.\n\n✅ **Status:** Kód zadán. Čeká na schválení."
			
			s.ChannelMessageEditComplex(&discordgo.MessageEdit{
				ID:         msgID,
				Channel:    v.Config.VerificationChannel,
				Embeds:     &[]*discordgo.MessageEmbed{embed},
				Components: &comps,
			})
		}
	}
}

func (v *VerificationService) HandleApprove(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	if v.Config.VerifiedRole != "" {
		err := s.GuildMemberRoleRemove(i.GuildID, userID, v.Config.VerifiedRole)
		if err != nil {
			log.Printf("Error removing role from %s: %v", userID, err)
		}
	}

	key := fmt.Sprintf("verify:state:%s", userID)
	state, _ := redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
	
	redis_client.Client.HSet(redis_client.Ctx, key, "status", "APPROVED")
	now := time.Now()
	redis_client.Client.HSet(redis_client.Ctx, key, "approved_at", now.Unix())

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

	joinTime := time.Unix(v.parseInt(state["created_at"]), 0)
	codeTime := time.Unix(v.parseInt(state["code_entered_at"]), 0)

	logContent := fmt.Sprintf("**Uživatel ověřen:**\n\n"+
		"**Uživatel:** <@%s> (%s)\n"+
		"**ID:** %s\n"+
		"**Účet vytvořen:** <t:%d:F> (<t:%d:R>)\n"+
		"**Věk účtu:** %s\n"+
		"**Avatar:** %s\n\n"+
		"Automaticky mu byla přidělena ověřovací role.\n\n"+
		"**Časový průběh:**\n"+
		"• Připojení: %s\n"+
		"• Zadání kódu: %s\n"+
		"• Schválení: %s\n\n"+
		"**Moderátor:** Schválil <@%s>",
		userID, username, userID, creationTime, creationTime, ageStr, avatar,
		joinTime.Format("2006-01-02 15:04:05"),
		codeTime.Format("2006-01-02 15:04:05"),
		now.Format("2006-01-02 15:04:05"),
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
