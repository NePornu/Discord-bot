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

func (v *VerificationService) GenerateOTP() string {
	const charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" // Sans ambiguous chars
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
			{Name: "Uživatel", Value: fmt.Sprintf("%#v", m.User.Mention()), Inline: true},
			{Name: "ID", Value: m.User.ID, Inline: true},
			{Name: "Vytvořen", Value: fmt.Sprintf("<t:%d:R>", m.User.ID), Inline: true}, // Mock for now
		},
	}

	msg, err := s.ChannelMessageSendEmbed(v.Config.VerifLogChannel, embed)
	if err == nil {
		// Store log message ID in redis to update later
		key := fmt.Sprintf("verify:state:%s", m.User.ID)
		redis_client.Client.HSet(redis_client.Ctx, key, "log_msg_id", msg.ID)
	}
}

func (v *VerificationService) OnMessageCreate(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID != "" { // Only care about DM
		return
	}

	uid := m.Author.ID
	key := fmt.Sprintf("verify:state:%s", uid)

	state, err := redis_client.Client.HAll(redis_client.Ctx, key).Result() // Typing fix needed later
	if err != nil || len(state) == 0 {
		return
	}

	if state["status"] == "APPROVED" {
		return
	}

	userInput := strings.TrimSpace(m.Content)
	otp := state["otp"]
	globalCode := v.Config.VerificationCode

	if userInput == otp || (globalCode != "" && strings.ToUpper(userInput) == strings.ToUpper(globalCode)) {
		// Correct code
		redis_client.Client.HSet(redis_client.Ctx, key, "status", "WAITING_FOR_APPROVAL")
		redis_client.Client.HSet(redis_client.Ctx, key, "code_entered_at", time.Now().Unix())

		s.ChannelMessageSend(m.ChannelID, "✅ **Kód je správný.** Nyní prosím čekej, než moderátor potvrdí tvůj přístup.")
		v.notifyMods(s, uid)
	} else {
		// Incorrect code
		redis_client.Client.HIncrBy(redis_client.Ctx, key, "attempts", 1)
		s.ChannelMessageSend(m.ChannelID, "❌ **Špatný kód.** Zkus to znovu.")
	}
}

func (v *VerificationService) notifyMods(s *discordgo.Session, userID string) {
	if v.Config.VerificationChannel == "" {
		return
	}

	// Update the initial join message with an "Approve" button
	key := fmt.Sprintf("verify:state:%s", userID)
	logMsgID, _ := redis_client.Client.HGet(redis_client.Ctx, key, "log_msg_id").Result()

	if logMsgID != "" {
		// Create ActionRow with Approve button
		btn := discordgo.Button{
			Label:    "Schválit (Approve)",
			Style:    discordgo.SuccessButton,
			CustomID: "verif_approve:" + userID,
			Emoji:    discordgo.ButtonEmoji{Name: "✅"},
		}

		s.ChannelMessageEditComplex(&discordgo.MessageEdit{
			ID:      logMsgID,
			Channel: v.Config.VerifLogChannel,
			Components: []discordgo.MessageComponent{
				discordgo.ActionsRow{
					Components: []discordgo.MessageComponent{btn},
				},
			},
		})
	}
}
