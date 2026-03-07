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

	switch customID {
	case "verify_button":
		// Reserved for future use
	case "sso_verify_button":
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "🔗 Pro verifikaci přes SSO použij `/verify nepornu` nebo klikni na odkaz v dashboardu.",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
	}
}

func (v *VerificationService) HandleVerifyCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	if len(options) == 0 {
		return
	}
	subcommand := options[0].Name

	switch subcommand {
	case "bypass":
		// Permission check: only those who can kick members can bypass
		if (i.Member.Permissions & discordgo.PermissionKickMembers) == 0 {
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: "❌ Nemáš oprávnění pro bypass verifikace.",
					Flags:   discordgo.MessageFlagsEphemeral,
				},
			})
			return
		}

		targetUser := options[0].Options[0].UserValue(s)
		v.HandleApprove(s, i, targetUser.ID)

	case "set_bypass":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: "❌ Nemáš oprávnění pro nastavení bypass hesla.",
					Flags:   discordgo.MessageFlagsEphemeral,
				},
			})
			return
		}
		newPassword := options[0].Options[0].StringValue()
		redis_client.Client.Set(redis_client.Ctx, "verify:bypass_hash", newPassword, 0)
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "✅ Heslo nastaveno (ukládáno v plain textu v redis cache pro zpětnou kompatibilitu dočasně).",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})

	case "ping":
		otp := v.GenerateOTP()
		v.sendDM(s, i.Member.User.ID, otp)
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "✅ Testovací DM odesláno.",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})

	case "nepornu":
		v.handleSSOLink(s, i)
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
	if v.Config.VerifLogChannel == "" {
		return
	}

	embed := &discordgo.MessageEmbed{
		Title: "📥 Nový uživatel se připojil",
		Color: 0x3498db,
		Thumbnail: &discordgo.MessageEmbedThumbnail{
			URL: m.User.AvatarURL(""),
		},
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Uživatel", Value: m.User.Mention(), Inline: true},
			{Name: "ID", Value: m.User.ID, Inline: true},
			{Name: "Status", Value: "⏳ Čeká na zadání kódu...", Inline: false},
		},
	}

	msg, err := s.ChannelMessageSendEmbed(v.Config.VerifLogChannel, embed)
	if err == nil {
		key := fmt.Sprintf("verify:state:%s", m.User.ID)
		redis_client.Client.HSet(redis_client.Ctx, key, "log_msg_id", msg.ID)
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
	logMsgID, _ := redis_client.Client.HGet(redis_client.Ctx, key, "log_msg_id").Result()

	if logMsgID != "" {
		btn := discordgo.Button{
			Label:    "Schválit (Approve)",
			Style:    discordgo.SuccessButton,
			CustomID: "verif_approve:" + userID,
			Emoji:    &discordgo.ComponentEmoji{Name: "✅"},
		}

		comps := []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btn},
			},
		}

		s.ChannelMessageEditComplex(&discordgo.MessageEdit{
			ID:         logMsgID,
			Channel:    v.Config.VerifLogChannel,
			Components: &comps,
		})
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
	redis_client.Client.HSet(redis_client.Ctx, key, "status", "APPROVED")
	redis_client.Client.HSet(redis_client.Ctx, key, "approved_at", time.Now().Unix())

	v.confirmSuccess(s, userID)

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Content:    fmt.Sprintf("✅ **Uživatel <@%s> byl schválen moderátorem <@%s>.**", userID, i.Member.User.ID),
			Components: []discordgo.MessageComponent{},
		},
	})
}

func (v *VerificationService) handleSSOLink(s *discordgo.Session, i *discordgo.InteractionCreate) {
	embed := &discordgo.MessageEmbed{
		Title: "🔗 Propojení s NePornu ID",
		Description: "Tento příkaz slouží k propojení tvého Discord účtu s interním systémem NePornu (Keycloak).\n\n" +
			"1. Klikni na tlačítko **'Propojit účet'** níže.\n" +
			"2. Přihlas se svými údaji.\n" +
			"3. Po úspěšném přihlášení klikni na **'Ověřit stav'**.\n\n" +
			"*Tip: Pokud jsi E-kouč nebo Moderátor, automaticky získáš své role.*",
		Color: 0x3498db,
	}

	btnLink := discordgo.Button{
		Label: "Propojit účet (Link SSO)",
		URL:   "https://portal.nepornu.cz",
		Style: discordgo.LinkButton,
		Emoji: &discordgo.ComponentEmoji{Name: "🔑"},
	}

	btnStatus := discordgo.Button{
		Label:    "Ověřit stav (Check Status)",
		Style:    discordgo.PrimaryButton,
		CustomID: "sso_verify_button",
		Emoji:    &discordgo.ComponentEmoji{Name: "🔄"},
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Embeds: []*discordgo.MessageEmbed{embed},
			Components: []discordgo.MessageComponent{
				discordgo.ActionsRow{
					Components: []discordgo.MessageComponent{btnLink, btnStatus},
				},
			},
		},
	})
}

func (v *VerificationService) confirmSuccess(s *discordgo.Session, userID string) {
	channel, err := s.UserChannelCreate(userID)
	if err == nil {
		s.ChannelMessageSend(channel.ID, "✅ **Ověření úspěšné!** Vítej na serveru.")
	}
}
