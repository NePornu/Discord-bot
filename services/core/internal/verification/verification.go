package verification

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
	"github.com/nepornucz/discord-bot-core/internal/stats"
)

type VerificationService struct {
	Config *config.Config
}

func NewVerificationService(cfg *config.Config) *VerificationService {
	return &VerificationService{Config: cfg}
}

func (v *VerificationService) HandleButtonClick(s *discordgo.Session, i *discordgo.InteractionCreate) {
	customID := i.MessageComponentData().CustomID
	userID := v.GetUserIDFromInteraction(i)

	// Check for age restriction from previous attempts
	if redis_client.Client != nil {
		restrictedYear, err := redis_client.Client.Get(redis_client.Ctx, fmt.Sprintf("verify:restricted:%s", userID)).Result()
		if err == nil && restrictedYear != "" {
			birthYear, _ := strconv.Atoi(restrictedYear)
			if time.Now().Year()-birthYear < 15 {
				s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
					Type: discordgo.InteractionResponseChannelMessageWithSource,
					Data: &discordgo.InteractionResponseData{
						Content: "⚠️ Přístup na tento server ti byl dříve zamítnut z důvodu nízkého věku. Zkus to prosím znovu, až ti bude 15 let.",
						Flags:   discordgo.MessageFlagsEphemeral,
					},
				})
				return
			}
		}
	}

	if customID == "verif_start" || customID == "verif_start_v2" || customID == "verif_open_modal" {
		slog.Info("Opening modal for user", "userID", userID)
		v.HandleModalOpen(s, i)
		return
	}

	if customID == "verif_consent" {
		v.HandleConsentClick(s, i)
		return
	}

	// Admin Control Panel Buttons
	if strings.HasPrefix(customID, "admin_") {
		v.HandleAdminInteraction(s, i)
		return
	}

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
	case "onboarding":
		v.postPublicLogic(s, i)

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


	case "bulk-reverify":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleBulkReverify(s, i)

	case "reset-age", "reset":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleResetCommand(s, i)

	case "bulk-migrate":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleBulkMigrate(s, i)

	case "bulk-all":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleBulkAll(s, i)

	case "list-waiting":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleListWaiting(s, i)

	case "list-db":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleListDB(s, i)

	case "audit-ages":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleAuditAges(s, i)

	case "broadcast":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleBroadcast(s, i)

	case "toggle":
		v.HandleToggleNudge(s, i)

	case "admin":
		v.HandleAdminCommand(s, i)

	case "progress":
		v.HandleProgressCommand(s, i)

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

	case "redis-audit":
		if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
			content := "❌ Pouze pro administrátory."
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
			return
		}
		v.HandleRedisAudit(s, i)

	case "ping":
		v.sendVerificationDM(s, i.Member.User.ID)
		content := "✅ Testovací DM odesláno."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})

	}
}

func (v *VerificationService) sendVerificationDM(s *discordgo.Session, userID string) error {
	channel, err := s.UserChannelCreate(userID)
	if err != nil {
		slog.Error("Error creating DM channel", "userID", userID, "error", err)
		return err
	}

	embed := v.createOnboardingEmbed()
	btn := v.createOnboardingButton()

	_, err = s.ChannelMessageSendComplex(channel.ID, &discordgo.MessageSend{
		Embeds: []*discordgo.MessageEmbed{embed},
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btn},
			},
		},
	})
	return err
}

func (v *VerificationService) OnMemberJoin(s *discordgo.Session, m *discordgo.GuildMemberAdd) {
	slog.Debug("OnMemberJoin triggered", "user", m.User.Username, "id", m.User.ID)
	if m.User.Bot {
		return
	}

	// Record join in stats
	stats.RecordJoin(m.GuildID)

	// Check if already verified
	if redis_client.Client != nil {
		exists, _ := redis_client.Client.Exists(redis_client.Ctx, fmt.Sprintf("user:passport:%s", m.User.ID)).Result()
		if exists > 0 {
			slog.Info("User already verified, skipping verification join flow", "userID", m.User.ID, "username", m.User.Username)
			return
		}
	}

	// 1. Setup Lock to prevent duplicate handling across multiple bot instances
	lockKey := fmt.Sprintf("verify:dm_lock:%s", m.User.ID)
	if redis_client.Client != nil {
		locked, _ := redis_client.Client.SetNX(redis_client.Ctx, lockKey, "1", 30*time.Second).Result()
		if !locked {
			slog.Debug("Another instance is already handling join", "userID", m.User.ID)
			return
		}
	}

	// 2. Initial setup - add waiting role
	v.StartVerification(s, m.GuildID, m.User.ID, m.User.Username, m.User.Mention(), m.User.AvatarURL("1024"))
}

func (v *VerificationService) StartVerification(s *discordgo.Session, guildID, userID, username, mention, avatarURL string) {
	// 1. Setup Lock to avoid race conditions if called manually
	lockKey := fmt.Sprintf("verify:start_lock:%s", userID)
	if redis_client.Client != nil {
		locked, _ := redis_client.Client.SetNX(redis_client.Ctx, lockKey, "1", 10*time.Second).Result()
		if !locked {
			return
		}
		defer redis_client.Client.Del(redis_client.Ctx, lockKey)
	}

	// 2. Initial setup - add waiting role
	if v.Config.WaitingRoleID != "" {
		s.GuildMemberRoleAdd(guildID, userID, v.Config.WaitingRoleID)
	}

	// 3. Setup state in Redis
	key := fmt.Sprintf("verify:state:%s", userID)
	if redis_client.Client != nil {
		redis_client.Client.HSet(redis_client.Ctx, key, map[string]interface{}{
			"status":     "PENDING",
			"created_at": time.Now().Unix(),
		})
	}

	// 4. Send DM
	v.sendVerificationDM(s, userID)

	// 5. Log join in mod channel (čakárna-log)
	v.logVerificationStarted(s, guildID, userID, username, mention, avatarURL)
}

func (v *VerificationService) logVerificationStarted(s *discordgo.Session, guildID, userID, username, mention, avatarURL string) {
	logChannel := v.Config.VerificationChannel
	verifLogChannel := v.Config.VerifLogChannel
	if logChannel == "" {
		return
	}

	creationTime := v.getCreationTime(userID)
	
	msgContent := fmt.Sprintf("**Nový uživatel se připojil na server!**\n\n"+
		"**Uživatel:** %s (%s)\n"+
		"**ID:** %s\n"+
		"**Účet vytvořen:** <t:%d:F> (<t:%d:R>)\n"+
		"**Avatar:** [Odkaz](%s)\n\n"+
		"⏳ **Status:** Čeká na vyplnění věku...",
		mention, username, userID, creationTime, creationTime, avatarURL)

	// Create buttons for immediate moderator actions
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
			Components: []discordgo.MessageComponent{btnWarn, btnKick},
		},
	}

	slog.Debug("Sending verification log", "channel", logChannel)
	msg, err := s.ChannelMessageSendComplex(logChannel, &discordgo.MessageSend{
		Content:    msgContent,
		Components: comps,
	})
	if err != nil {
		slog.Error("Error sending verification log", "channel", logChannel, "error", err)
		return
	}

	// Also send to Verification Log channel if configured (without buttons usually)
	var auditMsgID string
	if verifLogChannel != "" && verifLogChannel != logChannel {
		auditMsg, err := s.ChannelMessageSend(verifLogChannel, msgContent)
		if err == nil {
			auditMsgID = auditMsg.ID
		}
	}

	key := fmt.Sprintf("verify:state:%s", userID)
	if redis_client.Client != nil {
		redis_client.Client.HSet(redis_client.Ctx, key, "approve_msg_id", msg.ID)
		if auditMsgID != "" {
			redis_client.Client.HSet(redis_client.Ctx, key, "audit_msg_id", auditMsgID)
		}
	}
}

func (v *VerificationService) OnMemberRemove(s *discordgo.Session, m *discordgo.GuildMemberRemove) {
	slog.Debug("OnMemberRemove triggered", "user", m.User.Username, "id", m.User.ID)

	key := fmt.Sprintf("verify:state:%s", m.User.ID)
	if redis_client.Client == nil {
		return
	}

	state, _ := redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
	if len(state) == 0 {
		return
	}

	// Only clean up if they weren't already approved
	if state["status"] == "APPROVED" {
		return
	}

	logChannel := v.Config.VerificationChannel
	msgID := state["approve_msg_id"]

	if logChannel != "" && msgID != "" {
		// 1. Delete the moderator notification
		err := s.ChannelMessageDelete(logChannel, msgID)
		if err != nil {
			slog.Error("Failed to delete mod notification on leave", "msgID", msgID, "error", err)
		} else {
			slog.Info("Deleted mod notification as user left during verification", "userID", m.User.ID)
		}
	}

	// 2. Log to verif-log channel
	if v.Config.VerifLogChannel != "" {
		leaveMsg := fmt.Sprintf("👋 **Uživatel opustil server během verifikace:** %s (%s)\nID: `%s`", 
			m.User.Mention(), m.User.Username, m.User.ID)
		s.ChannelMessageSend(v.Config.VerifLogChannel, leaveMsg)
	}

	// 3. Clean up Redis state
	redis_client.Client.Del(redis_client.Ctx, key)
}

func (v *VerificationService) OnMessageCreate(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot {
		return
	}

	// 1. Smart Nudge: Check if user is verified (Discord Guild only)
	if m.GuildID != "" && redis_client.Client != nil {
		// Check if nudging is globally enabled
		enabled, _ := redis_client.Client.Get(redis_client.Ctx, "verify:nudge_enabled").Result()
		if enabled != "1" {
			return
		}

		isVerified := false
		// Check Redis for passport
		exists, _ := redis_client.Client.Exists(redis_client.Ctx, fmt.Sprintf("user:passport:%s", m.Author.ID)).Result()
		if exists > 0 {
			isVerified = true
		}

		if !isVerified {
			// Check for rate limit on nudging (once per 24h per user)
			nudgeKey := fmt.Sprintf("verify:nudge:%s", m.Author.ID)
			alreadyNudged, _ := redis_client.Client.Get(redis_client.Ctx, nudgeKey).Result()
			if alreadyNudged == "" {
				// PATIENCE MODE: Only nudge after N messages
				patienceKey := fmt.Sprintf("verify:patience:%s", m.Author.ID)
				count, _ := redis_client.Client.Incr(redis_client.Ctx, patienceKey).Result()
				if count == 1 {
					redis_client.Client.Expire(redis_client.Ctx, patienceKey, 2*time.Hour)
				}
				
				if count >= 5 {
					slog.Info("Sending smart nudge to unverified user (Patience threshold reached)", "userID", m.Author.ID, "messages", count)
					redis_client.Client.Set(redis_client.Ctx, nudgeKey, "1", 24*time.Hour)
					redis_client.Client.Del(redis_client.Ctx, patienceKey)
					
					v.sendSmartNudgeDM(s, m.Author.ID)
				}
			}
		}
	}

	// Handle DM inputs (deprecated OTP, only button is used now)
	if m.GuildID == "" {
		// We can add a fallback message if they try to type something
		// but for now we just ignore to not spam users
	}
}

func (v *VerificationService) sendSmartNudgeDM(s *discordgo.Session, userID string) {
	channel, err := s.UserChannelCreate(userID)
	if err != nil {
		return
	}

	embed := v.createOnboardingEmbed()
	btn := v.createOnboardingButton()

	_, err = s.ChannelMessageSendComplex(channel.ID, &discordgo.MessageSend{
		Embeds: []*discordgo.MessageEmbed{embed},
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btn},
			},
		},
	})

	if err != nil {
		slog.Error("Failed to send smart nudge DM", "userID", userID, "error", err)
	}
}

func (v *VerificationService) notifyMods(s *discordgo.Session, userID string, ageCategory string) {
	logChannel := v.Config.VerificationChannel
	if logChannel == "" {
		return
	}
	key := fmt.Sprintf("verify:state:%s", userID)
	msgID := ""
	auditMsgID := ""
	if redis_client.Client != nil {
		state, _ := redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
		msgID = state["approve_msg_id"]
		auditMsgID = state["audit_msg_id"]
	}

	// 1. Update Actionable Log (Čakárna)
	if msgID != "" {
		btnApprove := discordgo.Button{
			Label:    "✅ Schválit",
			Style:    discordgo.SuccessButton,
			CustomID: "verif_approve:" + userID,
		}
		btnKick := discordgo.Button{
			Label:    "🚪 Vyhodit (Kick)",
			Style:    discordgo.DangerButton,
			CustomID: "verif_kick:" + userID,
		}

		comps := []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btnApprove, btnKick},
			},
		}

		msg, err := s.ChannelMessage(logChannel, msgID)
		if err == nil {
			newContent := v.getUpdatedStatusContent(msg.Content, ageCategory)
			s.ChannelMessageEditComplex(&discordgo.MessageEdit{
				ID:         msgID,
				Channel:    logChannel,
				Content:    &newContent,
				Components: &comps,
			})
		}
	}

	// 2. Update Audit Log (Permanent)
	verifLogChannel := v.Config.VerifLogChannel
	if auditMsgID != "" && verifLogChannel != "" && verifLogChannel != logChannel {
		msg, err := s.ChannelMessage(verifLogChannel, auditMsgID)
		if err == nil {
			newContent := v.getUpdatedStatusContent(msg.Content, ageCategory)
			s.ChannelMessageEdit(verifLogChannel, auditMsgID, newContent)
		}
	}
}

func (v *VerificationService) getUpdatedStatusContent(oldContent, ageCategory string) string {
	lines := strings.Split(oldContent, "\n")
	updated := false
	for idx, line := range lines {
		if strings.Contains(line, "Status:") {
			lines[idx] = fmt.Sprintf("✅ **Status:** Uživatel vyplnil údaje.\n**Kategorie:** **%s**", ageCategory)
			updated = true
			break
		}
	}
	if !updated {
		lines = append(lines, fmt.Sprintf("\n✅ **Status:** Uživatel vyplnil údaje.\n**Kategorie:** **%s**", ageCategory))
	}
	return strings.Join(lines, "\n")
}


func (v *VerificationService) HandleApprove(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	slog.Debug("HandleApprove triggered", "userID", userID)
	// 1. Manage roles - Remove waiting role only (as clarified: "verified není jen se odebere role")
	if v.Config.WaitingRoleID != "" {
		s.GuildMemberRoleRemove(i.GuildID, userID, v.Config.WaitingRoleID)
	}

	// 2. Send Greeting to Welcome Channel
	if v.Config.WelcomeChannel != "" {
		greeting := fmt.Sprintf("Nový člen se k nám připojil! Všichni přivítejme <@%s>! Nezapomeň se podívat do <#882936285738704896> a <#1280412941400932393>. Můžeš se představit v <#1191296600631431198>!", userID)
		s.ChannelMessageSend(v.Config.WelcomeChannel, greeting)
	}

	key := fmt.Sprintf("verify:state:%s", userID)
	lockKey := fmt.Sprintf("verify:approve_lock:%s", userID)

	if redis_client.Client != nil {
		// 1. Acquire lock to prevent concurrent approvals
		locked, _ := redis_client.Client.SetNX(redis_client.Ctx, lockKey, "1", 10*time.Second).Result()
		if !locked {
			slog.Debug("HandleApprove already in progress", "userID", userID)
			if i.Type == discordgo.InteractionMessageComponent {
				s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
					Type: discordgo.InteractionResponseChannelMessageWithSource,
					Data: &discordgo.InteractionResponseData{
						Content: "⚠️ Toto schválení již zpracovává jiný moderátor.",
						Flags:   discordgo.MessageFlagsEphemeral,
					},
				})
			}
			return
		}
		defer redis_client.Client.Del(redis_client.Ctx, lockKey)

		// 2. Check if already approved
		status, _ := redis_client.Client.HGet(redis_client.Ctx, key, "status").Result()
		if status == "APPROVED" {
			slog.Debug("User already approved", "userID", userID)
			if i.Type == discordgo.InteractionMessageComponent {
				s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
					Type: discordgo.InteractionResponseUpdateMessage,
					Data: &discordgo.InteractionResponseData{
						Content:    "✅ Uživatel již byl schválen.",
						Components: []discordgo.MessageComponent{},
					},
				})
			}
			return
		}
	}

	var state map[string]string
	now := time.Now()
	ageCategory := ""
	if redis_client.Client != nil {
		state, _ = redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
		ageCategory = state["age_category"]
		redis_client.Client.HSet(redis_client.Ctx, key, "status", "APPROVED")
		redis_client.Client.HSet(redis_client.Ctx, key, "approved_at", now.Unix())
	}

	// 3. ONLY remove waiting role (as requested: "jen odeber roli čekač")
	if v.Config.WaitingRoleID != "" {
		s.GuildMemberRoleRemove(i.GuildID, userID, v.Config.WaitingRoleID)
	}

	// 4. Update Passport with username for listing
	if redis_client.Client != nil {
		u, _ := s.User(userID)
		username := userID
		if u != nil {
			username = u.Username
		}
		passportKey := fmt.Sprintf("user:passport:%s", userID)
		birthYearStr := v.decrypt(state["birth_year"])
		passportData := fmt.Sprintf(`{"username": "%s", "age_category": "%s", "birth_year": %s}`, username, ageCategory, birthYearStr)
		encryptedPassport := v.encrypt(passportData)
		redis_client.Client.Set(redis_client.Ctx, passportKey, encryptedPassport, 0)
	}

	v.confirmSuccess(s, userID)

	// 6. Update Mod Log (Edit in place)
	u, _ := s.User(userID)
	username := userID
	if u != nil {
		username = u.Username
	}

	logContent := fmt.Sprintf("✅ **Uživatel ověřen:**\n\n"+
		"**Uživatel:** <@%s> (%s)\n"+
		"**ID:** %s\n"+
		"**Kategorie:** **%s**\n\n"+
		"**Časový průběh:**\n"+
		"• Připojení: <t:%d:F>\n"+
		"• Schválení: <t:%d:F>\n\n"+
		"**Moderátor:** Schválil <@%s>",
		userID, username, userID, ageCategory,
		v.parseInt(state["created_at"]),
		now.Unix(),
		v.GetUserIDFromInteraction(i))

	approveMsgID := state["approve_msg_id"]
	auditMsgID := state["audit_msg_id"]

	// 1. Delete Actionable Log (Čakárna) - Keep the queue clean
	if approveMsgID != "" && v.Config.VerificationChannel != "" {
		err := s.ChannelMessageDelete(v.Config.VerificationChannel, approveMsgID)
		if err != nil {
			slog.Error("Failed to delete actionable log on approval", "msgID", approveMsgID, "error", err)
		}
	}

	// 2. Update/Send Audit Log (Permanent)
	verifLogChannel := v.Config.VerifLogChannel
	if auditMsgID != "" && verifLogChannel != "" {
		_, err := s.ChannelMessageEdit(verifLogChannel, auditMsgID, logContent)
		if err != nil {
			slog.Error("Failed to edit audit log on approval", "msgID", auditMsgID, "error", err)
			s.ChannelMessageSend(verifLogChannel, logContent)
		}
	} else if verifLogChannel != "" {
		s.ChannelMessageSend(verifLogChannel, logContent)
	}

	// 3. Respond to moderator (Ephemeral confirmation)
	if i.Type == discordgo.InteractionMessageComponent {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: fmt.Sprintf("✅ **Uživatel <@%s> byl schválen.**\nČekací zpráva byla odstraněna a audit log aktualizován.", userID),
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
	} else {
		// Response for slash commands like /verify bypass
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &logContent,
		})
	}
}

func (v *VerificationService) HandleWarn(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	slog.Info("Moderator issued a warning during verification", "modID", i.Member.User.ID, "targetID", userID)
	
	// Create DM to the user
	dm, err := s.UserChannelCreate(userID)
	if err == nil {
		warningMsg := "⚠️ **Upozornění od moderátorů**\n\n" +
			"Byl jsi upozorněn moderátorem během procesu ověření. Prosím, ujisti se, že postupuješ podle pokynů a dodržuješ pravidla serveru.\n" +
			"Pokud máš potíže s ověřením, kontaktuj podporu (pokud je dostupná) nebo zkus kód zadat znovu."
		s.ChannelMessageSend(dm.ID, warningMsg)
	}

	content := fmt.Sprintf("⚠️ **Varování pro <@%s> bylo zaznamenáno a odesláno do DM.**", userID)
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: content,
			Flags:   discordgo.MessageFlagsEphemeral,
		},
	})
}

func (v *VerificationService) HandleKick(s *discordgo.Session, i *discordgo.InteractionCreate, userID string) {
	modUser := v.getUserFromInteraction(i)
	modName := "unknown"
	if modUser != nil {
		modName = modUser.Username
	}
	err := s.GuildMemberDeleteWithReason(i.GuildID, userID, fmt.Sprintf("Verification rejected by %s", modName))
	content := ""
	if err != nil {
		content = fmt.Sprintf("❌ Nepodařilo se vyhodit uživatele: %v", err)
	} else {
		modID := v.GetUserIDFromInteraction(i)
		content = fmt.Sprintf("🚪 **Uživatel <@%s> byl vyhozen moderátorem <@%s>.**", userID, modID)
	}
	
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Content:    content,
			Components: []discordgo.MessageComponent{},
		},
	})
}

func (v *VerificationService) HandleRetroConfirm(s *discordgo.Session, i *discordgo.InteractionCreate, ageGroup string) {
	// Deprecated in favor of Select Menu
}

func (v *VerificationService) HandleToggleNudge(s *discordgo.Session, i *discordgo.InteractionCreate) {
	if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
		content := "❌ Pouze pro administrátory."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	state := "0"
	msg := "🔴 **Smart Nudge VYPNUT.** Bot nebude nikoho pošťuchovat."
	
	enabled, _ := redis_client.Client.Get(redis_client.Ctx, "verify:nudge_enabled").Result()
	if enabled != "1" {
		state = "1"
		msg = "🟢 **Smart Nudge ZAPNUT.** Bot začne pošťuchovat neověřené členy (po 5 zprávách)."
	}

	redis_client.Client.Set(redis_client.Ctx, "verify:nudge_enabled", state, 0)

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &msg,
	})
	slog.Info("Smart Nudge toggle handled via slash command", "newState", state)
}

func (v *VerificationService) HandleAdminCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
		content := "❌ Pouze pro administrátory."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	embed, components := v.createAdminDashboard(s, i.GuildID)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds:     &[]*discordgo.MessageEmbed{embed},
		Components: &components,
	})
}

func (v *VerificationService) HandleModalOpen(s *discordgo.Session, i *discordgo.InteractionCreate) {
	err := s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseModal,
		Data: &discordgo.InteractionResponseData{
			CustomID: "verif_age_modal",
			Title:    "Pojďme tě ověřit! 🚀",
			Components: []discordgo.MessageComponent{
				discordgo.ActionsRow{
					Components: []discordgo.MessageComponent{
						discordgo.TextInput{
							CustomID:    "birth_year",
							Label:       "Tvůj rok narození (zůstane v bezpečí)",
							Style:       discordgo.TextInputShort,
							Placeholder: "Např. 2005",
							Required:    true,
							MinLength:   4,
							MaxLength:   4,
						},
					},
				},
			},
		},
	})
	if err != nil {
		slog.Error("Failed to open modal", "userID", v.GetUserIDFromInteraction(i), "error", err)
	} else {
		slog.Info("Modal opened successfully", "userID", v.GetUserIDFromInteraction(i))
	}
}

func (v *VerificationService) HandleModalSubmit(s *discordgo.Session, i *discordgo.InteractionCreate) {
	data := i.ModalSubmitData()
	if data.CustomID != "verif_age_modal" {
		return
	}

	yearStr := data.Components[0].(*discordgo.ActionsRow).Components[0].(*discordgo.TextInput).Value
	birthYear, err := strconv.Atoi(strings.TrimSpace(yearStr))
	if err != nil || birthYear < 1920 || birthYear > time.Now().Year() {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "❌ Neplatný rok narození. Zadejte prosím čtyřmístné číslo (např. 2005).",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
		return
	}

	age := time.Now().Year() - birthYear
	uid := v.GetUserIDFromInteraction(i)
	key := fmt.Sprintf("verify:state:%s", uid)

	if redis_client.Client != nil {
		ctx, cancel := redis_client.Timeout()
		defer cancel()
		err := redis_client.Client.HSet(ctx, key, "birth_year", v.encrypt(yearStr)).Err()
		if err != nil {
			slog.Error("Failed to save birth year to Redis", "userID", uid, "error", err)
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: "❌ Chyba při ukládání dat do databáze. Zkuste to prosím později.",
					Flags:   discordgo.MessageFlagsEphemeral,
				},
			})
			return
		}
	}

	if age < 15 {
		// Scenario A: Under 15 - Friendly Rejection + Safety Tips + Kick
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "✅ Informace byly odeslány do tvých soukromých zpráv.",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})

		// Save restriction to Redis to remember they are under 15 (TTL 30 days for retry)
		if redis_client.Client != nil {
			redis_client.Client.Set(redis_client.Ctx, fmt.Sprintf("verify:restricted:%s", uid), yearStr, 30*24*time.Hour)
			
			// Clean up moderator notification since they are auto-rejected
			approveMsgID, _ := redis_client.Client.HGet(redis_client.Ctx, key, "approve_msg_id").Result()
			if approveMsgID != "" && v.Config.VerificationChannel != "" {
				s.ChannelMessageDelete(v.Config.VerificationChannel, approveMsgID)
			}

			// Log to permanent verification log
			if v.Config.VerifLogChannel != "" {
				username := uid
				if i.Member != nil && i.Member.User != nil {
					username = i.Member.User.Username
				}
				rejectMsg := fmt.Sprintf("🚫 **Uživatel automaticky zamítnut (věk pod 15 let):** <@%s> (%s)\nRok narození: `%s`", 
					uid, username, yearStr)
				s.ChannelMessageSend(v.Config.VerifLogChannel, rejectMsg)
			}
		}

		v.sendMinorSafetyTips(s, uid)
		
		// Kick after a short delay to allow DM to arrive
		time.AfterFunc(5*time.Second, func() {
			s.GuildMemberDeleteWithReason(i.GuildID, uid, "Věk pod 15 let (automatický systém)")
		})
		return
	}

	if age >= 15 && age < 18 {
		// Scenario B: 15-17 - Needs Consent
		if redis_client.Client != nil {
			redis_client.Client.HSet(redis_client.Ctx, key, "age_category", "15-17")
		}

		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "✅ Poslední krok najdeš ve svých soukromých zprávách (potvrzení souhlasu).",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})

		v.sendConsentPrompt(s, uid)
		return
	}

	// Scenario C: 18+ - Wait for moderator approval
	if redis_client.Client != nil {
		redis_client.Client.HSet(redis_client.Ctx, key, "age_category", "18+")
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
		Content: "✅ Super! Tvá žádost byla odeslána k našim moderátorům. Jakmile ji schválí, hned tě pustíme dál. ⏳",
			Flags:   discordgo.MessageFlagsEphemeral,
		},
	})

	v.notifyMods(s, uid, "18+")
}

func (v *VerificationService) sendMinorSafetyTips(s *discordgo.Session, userID string) {
	channel, err := s.UserChannelCreate(userID)
	if err != nil {
		return
	}

	// Message 1: Friendly rejection
	msg1 := "**⚠️ Přístup zamítnut**\n\n" +
		"Je nám líto, ale tento server je určen pouze pro lidi starší 15 let. Z bezpečnostních důvodů tě nyní nemůžeme vpustit.\n\n" +
		"Pokud máš potíže, velmi ti doporučujeme vyhledat odborné poradenství. Pokud plánuješ sebepoškození či sebevraždu, vyhledej okamžitě pomoc. Doporučujeme ti v takovém případě zavolat na Linku bezpečí https://www.linkabezpeci.cz/pomoc či Modrou linku https://modralinka.cz/. Pokud ti není příjemné hovořit s někým přes telefon, Chat linky důvěry nabízí okamžitou pomoc skrze chatovací místnost https://www.linkabezpeci.cz/chat.\n\n" +
		"Ať se daří!"

	s.ChannelMessageSend(channel.ID, msg1)
}

func (v *VerificationService) sendConsentPrompt(s *discordgo.Session, userID string) {
	channel, err := s.UserChannelCreate(userID)
	if err != nil {
		return
	}

	msg := "**👪 Kategorie 15–17 let**\n\n" +
		"Abychom tě mohli pustit dál, musíš vědět, jak se u nás chovat bezpečně:\n" +
		"• Nesdílej své osobní údaje ani fotky.\n" +
		"• Nechoď na schůzky s lidmi z internetu bez doprovodu rodičů.\n" +
		"• Máš-li jakýkoliv „špatný pocit“ z jiného uživatele, hned napiš moderátorům.\n\n" +
		"Kliknutím na tlačítko potvrzuješ, že máš souhlas rodičů a bereš pravidla na vědomí."

	btn := discordgo.Button{
		Label:    "✅ Potvrzuji souhlas rodičů a pravidla",
		Style:    discordgo.SuccessButton,
		CustomID: "verif_consent",
	}

	s.ChannelMessageSendComplex(channel.ID, &discordgo.MessageSend{
		Content: msg,
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btn},
			},
		},
	})
}

func (v *VerificationService) HandleConsentClick(s *discordgo.Session, i *discordgo.InteractionCreate) {
	uid := v.GetUserIDFromInteraction(i)
	
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Content:    "✅ **Děkujeme.** Tvoje žádost byla předána moderátorům ke schválení. Prosím o trpělivost.",
			Components: []discordgo.MessageComponent{},
		},
	})

	v.notifyMods(s, uid, "15-17 (se souhlasem)")
}

func (v *VerificationService) calculateAge(birthDate time.Time) int {
	now := time.Now()
	years := now.Year() - birthDate.Year()
	if now.Month() < birthDate.Month() || (now.Month() == birthDate.Month() && now.Day() < birthDate.Day()) {
		years--
	}
	return years
}

func (v *VerificationService) HandleBulkReverify(s *discordgo.Session, i *discordgo.InteractionCreate) {
	// 1. Initial response
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer("⏳ **Hromadné ověřování spuštěno...** Prosím čekejte, procházím seznam členů."),
	})

	// 2. Fetch all members (this can be large, use pagination if needed, but for now we try State)
	_, err := s.Guild(i.GuildID)
	if err != nil {
		content := "❌ Nepodařilo se načíst data serveru."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	members, err := s.GuildMembers(i.GuildID, "", 1000)
	if err != nil {
		content := "❌ Nepodařilo se načíst seznam členů."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	verifiedRoleID := v.Config.VerifiedRole
	sentCount := 0
	skippedCount := 0

	for _, m := range members {
		if m.User.Bot {
			continue
		}

		// Check if they have the verified role
		hasVerifiedRole := false
		for _, roleID := range m.Roles {
			if roleID == verifiedRoleID {
				hasVerifiedRole = true
				break
			}
		}

		if !hasVerifiedRole {
			continue
		}

		// Check if they have the NEW passport in Redis
		key := fmt.Sprintf("user:passport:%s", m.User.ID)
		passport, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
		if err == nil && strings.Contains(passport, `"birth"`) {
			skippedCount++
			continue
		}

		// Send DM nudge
		v.sendReverificationDM(s, m.User.ID)
		sentCount++
		time.Sleep(100 * time.Millisecond) // Respect rate limits
	}

	content := fmt.Sprintf("✅ **Hromadné ověřování dokončeno!**\n\n"+
		"• Celkem odesláno DM: `%d` uživatelům\n"+
		"• Již ověřeno (přeskočeno): `%d` uživatelů", sentCount, skippedCount)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}

func (v *VerificationService) sendReverificationDM(s *discordgo.Session, userID string) {
	// Re-use the new verification DM logic
	v.sendVerificationDM(s, userID)
}

func (v *VerificationService) HandleBulkMigrate(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer("⏳ **Migrace verifikací spuštěna...**"),
	})

	targetChannel := "1459269521440506110"
	v.purgeChannel(s, targetChannel)

	waitingRoleID := "1179506149951811734"
	
	members, err := s.GuildMembers(i.GuildID, "", 1000)
	if err != nil {
		content := "❌ Nepodařilo se načíst seznam členů."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	count := 0
	skippedCount := 0
	renewedCount := 0
	for _, m := range members {
		if m.User.Bot {
			continue
		}

		hasRole := false
		for _, rID := range m.Roles {
			if rID == waitingRoleID {
				hasRole = true
				break
			}
		}

		if hasRole {
			key := fmt.Sprintf("verify:state:%s", m.User.ID)
			
			if redis_client.Client != nil {
				status, _ := redis_client.Client.HGet(redis_client.Ctx, key, "status").Result()
				
				if status == "APPROVED" {
					skippedCount++
					continue
				}

				if status == "PENDING" {
					// 1. Delete old moderator log if exists
					oldMsgID, _ := redis_client.Client.HGet(redis_client.Ctx, key, "approve_msg_id").Result()
					if oldMsgID != "" && v.Config.VerificationChannel != "" {
						s.ChannelMessageDelete(v.Config.VerificationChannel, oldMsgID)
					}

					// 2. Purge DMs
					v.purgeDMs(s, m.User.ID)
					
					// 3. Re-send and update
					v.sendVerificationDM(s, m.User.ID)
					v.logVerificationStarted(s, i.GuildID, m.User.ID, m.User.Username, m.User.Mention(), m.User.AvatarURL("1024"))
					
					redis_client.Client.HSet(redis_client.Ctx, key, "created_at", time.Now().Unix())
					renewedCount++
					time.Sleep(500 * time.Millisecond) // Extra delay for DM purge safety
					continue
				}

				// New migration (no status yet)
				redis_client.Client.HSet(redis_client.Ctx, key, map[string]interface{}{
					"status":     "PENDING",
					"created_at": time.Now().Unix(),
				})
			}

			// Send DM and Log
			v.sendVerificationDM(s, m.User.ID)
			v.logVerificationStarted(s, i.GuildID, m.User.ID, m.User.Username, m.User.Mention(), m.User.AvatarURL("1024"))

			count++
			time.Sleep(350 * time.Millisecond)
		}
	}

	content := fmt.Sprintf("✅ **Migrace dokončena!**\nKanál <#%s> byl promazán.\n\n• Nově obesláno: `%d` uživatelů\n• Obnoveno (již v procesu): `%d` uživatelů\n• Přeskočeno (hotovo): `%d`", targetChannel, count, renewedCount, skippedCount)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}

func (v *VerificationService) purgeDMs(s *discordgo.Session, userID string) {
	channel, err := s.UserChannelCreate(userID)
	if err != nil {
		return
	}

	msgs, err := s.ChannelMessages(channel.ID, 50, "", "", "") // Last 50 messages
	if err != nil {
		return
	}

	for _, m := range msgs {
		if m.Author.ID == s.State.User.ID {
			s.ChannelMessageDelete(channel.ID, m.ID)
			time.Sleep(150 * time.Millisecond)
		}
	}
}

func (v *VerificationService) purgeChannel(s *discordgo.Session, channelID string) {
	slog.Info("Purging channel", "channelID", channelID)
	for {
		msgs, err := s.ChannelMessages(channelID, 100, "", "", "")
		if err != nil || len(msgs) == 0 {
			break
		}

		for _, msg := range msgs {
			s.ChannelMessageDelete(channelID, msg.ID)
			time.Sleep(50 * time.Millisecond)
		}
	}
}

func (v *VerificationService) HandleBulkAll(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options[0].Options
	dryRun := false
	for _, opt := range options {
		if opt.Name == "dry-run" {
			dryRun = opt.BoolValue()
		}
	}

	statusMsg := "⏳ **Hromadné obesílání VŠECH členů spuštěno...**"
	if dryRun {
		statusMsg = "🔍 **TESTOVACÍ REŽIM: Počítám uživatele pro hromadné obeslání...**"
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer(statusMsg),
	})

	members, err := s.GuildMembers(i.GuildID, "", 1000)
	if err != nil {
		content := "❌ Nepodařilo se načíst seznam členů."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	count := 0
	failedCount := 0
	for _, m := range members {
		if m.User.Bot {
			continue
		}

		// Check if they already have a passport in Redis
		key := fmt.Sprintf("user:passport:%s", m.User.ID)
		exists, _ := redis_client.Client.Exists(redis_client.Ctx, key).Result()

		if exists == 0 {
			if !dryRun {
				// Try to send DM and check for error
				err := v.sendVerificationDM(s, m.User.ID)
				if err != nil {
					failedCount++
				} else {
					count++
					time.Sleep(250 * time.Millisecond)
				}
			} else {
				count++
			}
		}
	}

	resPrefix := "✅ **Hromadné obesílání dokončeno!**"
	if dryRun {
		resPrefix = "📊 **TEST DOKONČEN!** (Nic nebylo odesláno)"
	}

	content := fmt.Sprintf("%s\n\n• Cílových uživatelů: `%d`"+
		"\n• Úspěšně odesláno: `%d`"+
		"\n• Selhalo (vypnuté DM): `%d`", 
		resPrefix, count+failedCount, count, failedCount)
	
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}

func (v *VerificationService) HandleListDB(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer("⏳ **Načítám seznam z databáze...**"),
	})

	if redis_client.Client == nil {
		content := "❌ Databáze není dostupná."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	keys, _ := redis_client.Client.Keys(redis_client.Ctx, "user:passport:*").Result()
	if len(keys) == 0 {
		content := "📭 V databázi nejsou žádné záznamy."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	var list []string
	for _, key := range keys {
		val, _ := redis_client.Client.Get(redis_client.Ctx, key).Result()
		uid := strings.TrimPrefix(key, "user:passport:")
		
		valDec := v.decrypt(val)
		var data struct {
			Username    string `json:"username"`
			AgeCategory string `json:"age_category"`
		}
		
		if err := json.Unmarshal([]byte(valDec), &data); err == nil && data.Username != "" {
			list = append(list, fmt.Sprintf("- <@%s> **%s** (%s)", uid, data.Username, data.AgeCategory))
		} else {
			// Fallback for raw data or parsing failure
			list = append(list, fmt.Sprintf("- <@%s> `%s` (%s)", uid, uid, valDec))
		}
	}

	chunks := v.chunkStrings(list, 1500)
	for idx, chunk := range chunks {
		content := fmt.Sprintf("📋 **Seznam prověřených uživatelů (%d/%d):**\n\n%s", idx+1, len(chunks), strings.Join(chunk, "\n"))
		if idx == 0 {
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		} else {
			s.FollowupMessageCreate(i.Interaction, true, &discordgo.WebhookParams{
				Content: content,
			})
		}
	}
}


func pointer(s string) *string {
	return &s
}

func (v *VerificationService) createAdminDashboard(s *discordgo.Session, guildID string) (*discordgo.MessageEmbed, []discordgo.MessageComponent) {
	nudgeStatus := "🔴 VYPNUTO"
	if redis_client.Client != nil {
		enabled, _ := redis_client.Client.Get(redis_client.Ctx, "verify:nudge_enabled").Result()
		if enabled == "1" {
			nudgeStatus = "🟢 ZAPNUTO"
		}
	}

	statsText := v.getStatsString(s, guildID)

	embed := &discordgo.MessageEmbed{
		Title:       "🛠️ Správa Ověřování Členů",
		Description: fmt.Sprintf("**Stav Smart Nudge:** %s\n\n%s", nudgeStatus, statsText),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}

	row1 := discordgo.ActionsRow{
		Components: []discordgo.MessageComponent{
						discordgo.Button{Label: "Hromadný Broadcast", Style: discordgo.SecondaryButton, CustomID: "admin_broadcast", Emoji: &discordgo.ComponentEmoji{Name: "📢"}},
						discordgo.Button{Label: "Poslat Onboarding", Style: discordgo.SuccessButton, CustomID: "admin_post_onboarding", Emoji: &discordgo.ComponentEmoji{Name: "📬"}},
						discordgo.Button{Label: "Aktualizovat", Style: discordgo.SecondaryButton, CustomID: "admin_refresh", Emoji: &discordgo.ComponentEmoji{Name: "⏳"}},
		},
	}

	return embed, []discordgo.MessageComponent{row1}
}

func (v *VerificationService) HandleAdminInteraction(s *discordgo.Session, i *discordgo.InteractionCreate) {
	customID := i.MessageComponentData().CustomID
	slog.Info("Admin interaction triggered", "customID", customID)

	// Admin permissions check (only for dashboard actions)
	if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: "❌ Pouze správci.", Flags: discordgo.MessageFlagsEphemeral},
		})
		return
	}

	switch customID {
	case "admin_broadcast":
		v.HandleBroadcast(s, i)
		return // Response handled
	case "admin_post_onboarding":
		v.postPublicLogic(s, i)
		return
	case "admin_refresh":
		// Just refresh the dashboard below
	}

	// Refresh Dashboard
	embed, components := v.createAdminDashboard(s, i.GuildID)
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Embeds:     []*discordgo.MessageEmbed{embed},
			Components: components,
		},
	})
}



func (v *VerificationService) HandleBroadcast(s *discordgo.Session, i *discordgo.InteractionCreate) {
	msg := "📢 **Hromadná výzva aktivována.** Unverified uživatelé budou pošťouchnuti."
	if i.Type == discordgo.InteractionApplicationCommand {
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &msg})
	} else {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: msg, Flags: discordgo.MessageFlagsEphemeral},
		})
	}
}

func (v *VerificationService) getStatsString(s *discordgo.Session, guildID string) string {
	guild, err := s.State.Guild(guildID)
	if err != nil {
		guild, _ = s.Guild(guildID)
	}
	if guild == nil {
		return "⚠️ Nelze načíst data serveru."
	}

	totalMembers := guild.MemberCount
	totalVerified := 0
	keys, _ := redis_client.Client.Keys(redis_client.Ctx, "verify:state:*").Result()
	for _, key := range keys {
		val, _ := redis_client.Client.HGet(redis_client.Ctx, key, "status").Result()
		if val == "APPROVED" {
			totalVerified++
		}
	}
	percent := float64(totalVerified) / float64(totalMembers) * 100
	barLen := 15
	filled := int(float64(totalVerified) / float64(totalMembers) * float64(barLen))
	bar := ""
	for j := 0; j < barLen; j++ {
		if j < filled {
			bar += "▓"
		} else {
			bar += "░"
		}
	}

	return fmt.Sprintf("📈 **Postup:** `%s` **%.1f%%**\n👥 **Celkem:** `%d` | **Ověřeno:** `%d`",
		bar, percent, totalMembers, totalVerified)
}

func (v *VerificationService) postPublicLogic(s *discordgo.Session, i *discordgo.InteractionCreate) {
	embed := v.createOnboardingEmbed()
	btn := v.createOnboardingButton()

	s.ChannelMessageSendComplex(i.ChannelID, &discordgo.MessageSend{
		Embeds: []*discordgo.MessageEmbed{embed},
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btn},
			},
		},
	})

	if i.Type == discordgo.InteractionApplicationCommand || i.Type == discordgo.InteractionMessageComponent {
		slog.Info("Onboarding menu posted", "by", i.Member.User.Username)
		if i.Type == discordgo.InteractionMessageComponent {
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{Content: "✅ Menu bylo odesláno.", Flags: discordgo.MessageFlagsEphemeral},
			})
		}
	}
}

func (v *VerificationService) createOnboardingEmbed() *discordgo.MessageEmbed {
	return &discordgo.MessageEmbed{
		Title: "🔒 Ověřený vstup na server NePornu",
		Description: "Vítej v naší komunitě! Pro přístup na server je nutné potvrdit svůj věk:\n\n" +
			"Kliknutím na tlačítko a zadáním roku narození potvrzuješ svůj věk a souhlas s pravidly serveru:",
		Color: 0x5865F2,
	}
}

func (v *VerificationService) createOnboardingButton() discordgo.Button {
	return discordgo.Button{
		Label:    "🚀 Zahájit ověření",
		Style:    discordgo.SuccessButton,
		CustomID: "verif_open_modal",
	}
}

func (v *VerificationService) HandleProgressCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	if redis_client.Client == nil {
		return
	}
	resp := v.getStatsString(s, i.GuildID)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &resp})
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

func (v *VerificationService) GetUserIDFromInteraction(i *discordgo.InteractionCreate) string {
	if i.Member != nil && i.Member.User != nil {
		return i.Member.User.ID
	}
	if i.User != nil {
		return i.User.ID
	}
	return ""
}

func (v *VerificationService) getUserFromInteraction(i *discordgo.InteractionCreate) *discordgo.User {
	if i.Member != nil && i.Member.User != nil {
		return i.Member.User
	}
	if i.User != nil {
		return i.User
	}
	return nil
}

func (v *VerificationService) HandleListWaiting(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer("⏳ **Generuji seznam uživatelů v čekárně...**"),
	})

	waitingRoleID := "1179506149951811734"
	members, err := s.GuildMembers(i.GuildID, "", 1000)
	if err != nil {
		content := "❌ Nepodařilo se načíst seznam členů."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	var list []string
	for _, m := range members {
		for _, rID := range m.Roles {
			if rID == waitingRoleID {
				list = append(list, fmt.Sprintf("- %s (%s) ID: `%s`", m.User.Mention(), m.User.Username, m.User.ID))
				break
			}
		}
	}

	if len(list) == 0 {
		content := "📭 V čekárně nejsou žádní uživatelé."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	chunks := v.chunkStrings(list, 1500)
	for idx, chunk := range chunks {
		content := fmt.Sprintf("📋 **Seznam uživatelů v čekárně (%d/%d):**\n\n%s", idx+1, len(chunks), strings.Join(chunk, "\n"))
		if idx == 0 {
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		} else {
			s.FollowupMessageCreate(i.Interaction, true, &discordgo.WebhookParams{
				Content: content,
			})
		}
	}
}

func (v *VerificationService) chunkStrings(slice []string, limit int) [][]string {
	var chunks [][]string
	var currentChunk []string
	currentLen := 0

	for _, s := range slice {
		if currentLen+len(s)+1 > limit {
			chunks = append(chunks, currentChunk)
			currentChunk = []string{}
			currentLen = 0
		}
		currentChunk = append(currentChunk, s)
		currentLen += len(s) + 1
	}
	if len(currentChunk) > 0 {
		chunks = append(chunks, currentChunk)
	}
	return chunks
}

func (v *VerificationService) confirmSuccess(s *discordgo.Session, userID string) {
	dm, err := s.UserChannelCreate(userID)
	if err != nil {
		return
	}

	msg := "✅ **Hurá! Ověření proběhlo úspěšně.**"
	s.ChannelMessageSend(dm.ID, msg)
}
func (v *VerificationService) encrypt(plaintext string) string {
	if v.Config.VerificationSecret == "" {
		return plaintext
	}

	key := sha256.Sum256([]byte(v.Config.VerificationSecret))
	block, err := aes.NewCipher(key[:])
	if err != nil {
		slog.Error("Cipher setup error", "error", err)
		return plaintext
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		slog.Error("GCM setup error", "error", err)
		return plaintext
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		slog.Error("Nonce generation error", "error", err)
		return plaintext
	}

	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext)
}

func (v *VerificationService) decrypt(ciphertextStr string) string {
	if v.Config.VerificationSecret == "" || ciphertextStr == "" {
		return ciphertextStr
	}

	// Heuristic: if it doesn't look like base64 or is too short, assume plaintext
	if !v.isBase64(ciphertextStr) {
		return ciphertextStr
	}

	ciphertext, err := base64.StdEncoding.DecodeString(ciphertextStr)
	if err != nil {
		return ciphertextStr
	}

	key := sha256.Sum256([]byte(v.Config.VerificationSecret))
	block, err := aes.NewCipher(key[:])
	if err != nil {
		return ciphertextStr
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return ciphertextStr
	}

	nonceSize := gcm.NonceSize()
	if len(ciphertext) < nonceSize {
		return ciphertextStr
	}

	nonce, encryptedData := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, encryptedData, nil)
	if err != nil {
		// Decryption failed, likely plaintext that happened to be valid base64
		return ciphertextStr
	}

	return string(plaintext)
}

func (v *VerificationService) isBase64(s string) bool {
	_, err := base64.StdEncoding.DecodeString(s)
	return err == nil && len(s) > 16 // Encryption output should be at least nonce (12) + tag (16)
}

func (v *VerificationService) HandleAuditAges(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer("⏳ **Spouštím audit věku...** Prohledávám historii zpráv (to může chvíli trvat)."),
	})

	channels, err := s.GuildChannels(i.GuildID)
	if err != nil {
		content := "❌ Nepodařilo se načíst seznam kanálů."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	// Regex patterns for age detection in Czech and Slovak
	patterns := []string{
		`(?i)je\s*mi\s*(?:něco\s*málo\s*přes\s*|kolem\s*|asi\s*)?(\d{1,2})`,
		`(?i)mám\s*(?:vlastně\s*)?(\d{1,2})\s*(?:let|roků|rokov|rok|roka)`,
		`(?i)ve\s*věku\s*(\d{1,2})`,
		`(?i)v\s*mém\s*věku\s*(\d{1,2})`,
		`(?i)(\d{1,2})\s*(?:let|roků|rokov|rok|roka)`,
		`(?i)v\s*roce\s*(\d{4})`, // Capture year of birth/event
	}
	var regexes []*regexp.Regexp
	for _, p := range patterns {
		regexes = append(regexes, regexp.MustCompile(p))
	}

	results := make(map[string][]string) // userID -> list of matched messages
	messageCount := 0

	for _, ch := range channels {
		if ch.Type != discordgo.ChannelTypeGuildText {
			continue
		}

		// Progress report
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: pointer(fmt.Sprintf("⏳ **Audit věku:** Prohledávám kanál <#%s>...", ch.ID)),
		})

		// Fetch last 3000 messages from each text channel (30 batches of 100)
		beforeID := ""
		for batch := 0; batch < 30; batch++ {
			msgs, err := s.ChannelMessages(ch.ID, 100, beforeID, "", "")
			if err != nil || len(msgs) == 0 {
				break
			}

			for _, m := range msgs {
				if m.Author.Bot {
					continue
				}
				messageCount++

				for _, re := range regexes {
					matches := re.FindStringSubmatch(m.Content)
					if len(matches) > 1 {
						ageVal := matches[1]
						// Filter out unlikely ages (only 10-60)
						ageInt, _ := strconv.Atoi(ageVal)
						if ageInt > 10 && ageInt < 60 {
							line := fmt.Sprintf("[%s] **%s**: \"%s\"", ch.Name, m.Author.Username, m.Content)
							results[m.Author.ID] = append(results[m.Author.ID], line)
							break
						}
					}
				}
				beforeID = m.ID
			}
			time.Sleep(50 * time.Millisecond) // Respect rate limits
		}
	}

	if len(results) == 0 {
		content := fmt.Sprintf("✅ **Audit dokončen.**\nProhledáno `%d` zpráv, nebyly nalezeny žádné zjevné zmínky o věku.", messageCount)
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	var report []string
	for uid, mentions := range results {
		report = append(report, fmt.Sprintf("👤 <@%s> (%d zmínek):\n%s", uid, len(mentions), strings.Join(mentions, "\n")))
	}

	chunks := v.chunkStrings(report, 1500)
	for idx, chunk := range chunks {
		header := ""
		if idx == 0 {
			header = fmt.Sprintf("🔍 **Výsledky auditu věku (%d nalezených uživatelů):**\n\n", len(results))
		}
		content := header + strings.Join(chunk, "\n\n")
		
		if idx == 0 {
			s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		} else {
			s.FollowupMessageCreate(i.Interaction, true, &discordgo.WebhookParams{Content: content})
		}
	}
}
func (v *VerificationService) HandleRedisAudit(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: pointer("🔍 **Provádím audit Redis databáze...**"),
	})

	if redis_client.Client == nil {
		content := "❌ Redis není připojen."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	stateKeys, _ := redis_client.Client.Keys(redis_client.Ctx, "verify:state:*").Result()
	passportKeys, _ := redis_client.Client.Keys(redis_client.Ctx, "user:passport:*").Result()

	var report []string
	report = append(report, fmt.Sprintf("📊 **Statistika klíčů:**\n- `verify:state:*`: `%d` klíčů\n- `user:passport:*`: `%d` klíčů\n", len(stateKeys), len(passportKeys)))

	// Sample data from state
	if len(stateKeys) > 0 {
		report = append(report, "\n📝 **Ukázka stavů (verify:state):**")
		maxSample := 5
		if len(stateKeys) < maxSample {
			maxSample = len(stateKeys)
		}
		for _, k := range stateKeys[:maxSample] {
			data, _ := redis_client.Client.HGetAll(redis_client.Ctx, k).Result()
			birthYearEnc := data["birth_year"]
			birthYearDec := v.decrypt(birthYearEnc)
			
			encryptSuffix := ""
			if birthYearEnc != birthYearDec {
				encryptSuffix = " 🔒 (Zašifrováno)"
			}

			report = append(report, fmt.Sprintf("- `%s`: status=`%s`, birth_year=`%s` %s", k, data["status"], birthYearDec, encryptSuffix))
		}
	}

	// Sample data from passports
	if len(passportKeys) > 0 {
		report = append(report, "\n🛂 **Ukázka pasů (user:passport):**")
		maxSample := 5
		if len(passportKeys) < maxSample {
			maxSample = len(passportKeys)
		}
		for _, k := range passportKeys[:maxSample] {
			val, _ := redis_client.Client.Get(redis_client.Ctx, k).Result()
			valDec := v.decrypt(val)
			
			encryptSuffix := ""
			if val != valDec {
				encryptSuffix = " 🔒 (Zašifrováno)"
			}
			
			// Show only first 50 chars of Decrypted value for safety
			displayVal := valDec
			if len(displayVal) > 60 {
				displayVal = displayVal[:57] + "..."
			}

			report = append(report, fmt.Sprintf("- `%s`: `%s` %s", k, displayVal, encryptSuffix))
		}
	}

	content := strings.Join(report, "\n")
	if len(content) > 2000 {
		content = content[:1990] + "..."
	}
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}

func (v *VerificationService) HandleResetCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options[0].Options
	targetUser := options[0].UserValue(s)

	if redis_client.Client != nil {
		ctx, cancel := redis_client.Timeout()
		defer cancel()

		// 1. Clear all session and passport data
		keysToDelete := []string{
			fmt.Sprintf("verify:state:%s", targetUser.ID),
			fmt.Sprintf("user:passport:%s", targetUser.ID),
			fmt.Sprintf("verify:restricted:%s", targetUser.ID),
			fmt.Sprintf("verify:nudge:%s", targetUser.ID),
			fmt.Sprintf("verify:patience:%s", targetUser.ID),
		}

		for _, key := range keysToDelete {
			redis_client.Client.Del(ctx, key)
		}
	}

	// 2. Remove verified role if they have it (the system typically only removes 'waiting', but let's be safe)
	if v.Config.VerifiedRole != "" {
		s.GuildMemberRoleRemove(i.GuildID, targetUser.ID, v.Config.VerifiedRole)
	}

	// 3. Re-trigger verification flow
	v.StartVerification(s, i.GuildID, targetUser.ID, targetUser.Username, targetUser.Mention(), targetUser.AvatarURL("1024"))

	content := fmt.Sprintf("✅ Proces ověření pro uživatele <@%s> byl kompletně resetován.\n- Redis data smazána\n- Role aktualizovány\n- Onboarding DM odesláno", targetUser.ID)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}
