package automod

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type Filter struct {
	ID              int      `json:"id,omitempty"`
	Pattern         string   `json:"pattern"`
	AllowedRoles    []string `json:"allowed_roles"`
	AllowedChannels []string `json:"allowed_channels"`
	Whitelist       []string `json:"whitelist"`
	Action          string   `json:"action"`
}

type PendingMessage struct {
	Content      string `json:"content"`
	AuthorID     string `json:"author_id"`
	AuthorName   string `json:"author_name"`
	AuthorAvatar string `json:"author_avatar"`
	ChannelID    string `json:"channel_id"`
	GuildID      string `json:"guild_id"`
}

type AutoModService struct {
	Config           *config.Config
	ApprovalChannel  string
}

func NewAutoModService(cfg *config.Config) *AutoModService {
	return &AutoModService{
		Config:          cfg,
		ApprovalChannel: cfg.AlertChannelID, // Fallback to mod/alert channel
	}
}

func (a *AutoModService) GetFilters(guildID string) ([]Filter, error) {
	if redis_client.Client == nil {
		return nil, nil
	}
	key := fmt.Sprintf("automod:filters:%s", guildID)
	val, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err != nil {
		return nil, nil // No filters
	}

	var filters []Filter
	err = json.Unmarshal([]byte(val), &filters)
	return filters, err
}

func (a *AutoModService) OnMessage(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID == "" {
		return
	}
	a.ProcessAutoMod(s, m.Message)
}

func (a *AutoModService) OnMessageUpdate(s *discordgo.Session, m *discordgo.MessageUpdate) {
	if m.Author == nil || m.Author.Bot || m.GuildID == "" {
		return
	}
	a.ProcessAutoMod(s, m.Message)
}

func (a *AutoModService) ProcessAutoMod(s *discordgo.Session, m *discordgo.Message) {
	filters, _ := a.GetFilters(m.GuildID)
	if len(filters) == 0 {
		return
	}

	for _, f := range filters {
		re, err := regexp.Compile("(?i)" + f.Pattern)
		if err != nil {
			continue
		}

		if re.MatchString(m.Content) {
			// Check exemptions
			if a.isExempt(s, m, f) {
				continue
			}

			// Match found!
			a.HandleViolation(s, m, f)
			return
		}
	}
}

func (a *AutoModService) isExempt(s *discordgo.Session, m *discordgo.Message, f Filter) bool {
	// 1. Channel exemption
	for _, cid := range f.AllowedChannels {
		if cid == m.ChannelID {
			return true
		}
	}

	// 2. Role exemption
	if m.Member != nil {
		for _, rid := range f.AllowedRoles {
			for _, userRid := range m.Member.Roles {
				if rid == userRid {
					return true
				}
			}
		}
	}

	// 3. Simple containment check for whitelist (can be refined)
	for _, w := range f.Whitelist {
		if strings.Contains(strings.ToLower(m.Content), strings.ToLower(w)) {
			// Simple check for now
		}
	}

	return false
}

func (a *AutoModService) HandleViolation(s *discordgo.Session, m *discordgo.Message, f Filter) {
	// 1. Delete message
	s.ChannelMessageDelete(m.ChannelID, m.ID)

	// 2. Handle Action
	if f.Action == "auto_reject" {
		a.logViolation(s, m, "Auto-Rejected")
		return
	}

	// 3. Action is "approve"
	a.queueForApproval(s, m)
}

func (a *AutoModService) queueForApproval(s *discordgo.Session, m *discordgo.Message) {
	// Store in Redis
	msgData := PendingMessage{
		Content:      m.Content,
		AuthorID:     m.Author.ID,
		AuthorName:   m.Author.Username,
		AuthorAvatar: m.Author.AvatarURL(""),
		ChannelID:    m.ChannelID,
		GuildID:      m.GuildID,
	}
	data, _ := json.Marshal(msgData)
	key := fmt.Sprintf("automod:pending:%s", m.ID)
	if redis_client.Client != nil {
		redis_client.Client.Set(redis_client.Ctx, key, data, 24*time.Hour)
	}

	// Send to approval channel
	if a.ApprovalChannel == "" {
		return
	}

	embed := &discordgo.MessageEmbed{
		Title:       "🛡️ AutoMod: Message Awaiting Approval",
		Description: m.Content,
		Color:       0xffa500, // Orange
		Author: &discordgo.MessageEmbedAuthor{
			Name:    fmt.Sprintf("%s (%s)", m.Author.Username, m.Author.ID),
			IconURL: m.Author.AvatarURL(""),
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Message ID: %s | Channel: %s", m.ID, m.ChannelID),
		},
	}

	btnApprove := discordgo.Button{
		Label:    "Approve",
		Style:    discordgo.SuccessButton,
		CustomID: "automod_approve:" + m.ID,
	}
	btnReject := discordgo.Button{
		Label:    "Reject",
		Style:    discordgo.DangerButton,
		CustomID: "automod_reject:" + m.ID,
	}

	s.ChannelMessageSendComplex(a.ApprovalChannel, &discordgo.MessageSend{
		Embeds: []*discordgo.MessageEmbed{embed},
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btnApprove, btnReject},
			},
		},
	})
}

func (a *AutoModService) logViolation(s *discordgo.Session, m *discordgo.Message, reason string) {
	if a.ApprovalChannel == "" {
		return
	}
	embed := &discordgo.MessageEmbed{
		Title:       fmt.Sprintf("🛡️ AutoMod: %s", reason),
		Description: m.Content,
		Color:       0xff0000, // Red
		Author: &discordgo.MessageEmbedAuthor{
			Name:    fmt.Sprintf("%s (%s)", m.Author.Username, m.Author.ID),
			IconURL: m.Author.AvatarURL(""),
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Channel: %s", m.ChannelID),
		},
	}
	s.ChannelMessageSendEmbed(a.ApprovalChannel, embed)
}

func (a *AutoModService) HandleAutoModCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: 64, // Ephemeral
		},
	})

	options := i.ApplicationCommandData().Options
	subcommand := options[0].Name

	switch subcommand {
	case "filter-add":
		a.handleFilterAdd(s, i)
	case "filter-list":
		a.handleFilterList(s, i)
	case "filter-remove":
		a.handleFilterRemove(s, i)
	}
}

func (a *AutoModService) handleFilterAdd(s *discordgo.Session, i *discordgo.InteractionCreate) {
	opts := i.ApplicationCommandData().Options[0].Options
	var f Filter
	f.Action = "approve"

	for _, opt := range opts {
		switch opt.Name {
		case "pattern":
			f.Pattern = opt.StringValue()
		case "action":
			f.Action = opt.StringValue()
		case "roles":
			f.AllowedRoles = strings.Split(opt.StringValue(), ",")
		case "channels":
			f.AllowedChannels = strings.Split(opt.StringValue(), ",")
		}
	}

	// Validate Regex
	if _, err := regexp.Compile(f.Pattern); err != nil {
		content := "❌ Neplatný regulární výraz."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	filters, _ := a.GetFilters(i.GuildID)
	filters = append(filters, f)
	a.SaveFilters(i.GuildID, filters)

	content := fmt.Sprintf("✅ Filtr přidán: `%s` [%s]", f.Pattern, f.Action)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}

func (a *AutoModService) handleFilterList(s *discordgo.Session, i *discordgo.InteractionCreate) {
	filters, _ := a.GetFilters(i.GuildID)
	if len(filters) == 0 {
		content := "📭 Žádné aktivní filtry."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	var sb strings.Builder
	sb.WriteString("🛡️ **Aktivní AutoMod Filtry:**\n")
	for i, f := range filters {
		sb.WriteString(fmt.Sprintf("%d. `%s` [%s]\n", i+1, f.Pattern, f.Action))
	}

	content := sb.String()
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}

func (a *AutoModService) handleFilterRemove(s *discordgo.Session, i *discordgo.InteractionCreate) {
	index := int(i.ApplicationCommandData().Options[0].Options[0].IntValue()) - 1
	filters, _ := a.GetFilters(i.GuildID)

	if index < 0 || index >= len(filters) {
		content := "❌ Neplatný index."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	removed := filters[index]
	filters = append(filters[:index], filters[index+1:]...)
	a.SaveFilters(i.GuildID, filters)

	content := fmt.Sprintf("✅ Odstraněn filtr: `%s`", removed.Pattern)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}

func (a *AutoModService) SaveFilters(guildID string, filters []Filter) {
	if redis_client.Client == nil {
		return
	}
	key := fmt.Sprintf("automod:filters:%s", guildID)
	data, _ := json.Marshal(filters)
	redis_client.Client.Set(redis_client.Ctx, key, data, 0)
}

func (a *AutoModService) HandleInteraction(s *discordgo.Session, i *discordgo.InteractionCreate) {
	data := i.MessageComponentData()
	customID := data.CustomID
	
	if strings.HasPrefix(customID, "automod_approve:") {
		msgID := strings.TrimPrefix(customID, "automod_approve:")
		a.handleApprove(s, i, msgID)
		return
	}
	
	if strings.HasPrefix(customID, "automod_reject:") {
		msgID := strings.TrimPrefix(customID, "automod_reject:")
		a.handleReject(s, i, msgID)
		return
	}
}

func (a *AutoModService) handleApprove(s *discordgo.Session, i *discordgo.InteractionCreate, msgID string) {
	key := fmt.Sprintf("automod:pending:%s", msgID)
	val, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err != nil {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: "⚠️ Data vypršela nebo nebyla nalezena.", Flags: 64},
		})
		return
	}

	var data PendingMessage
	json.Unmarshal([]byte(val), &data)

	// Restore via Webhook
	a.restoreMessage(s, data)

	redis_client.Client.Del(redis_client.Ctx, key)

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Content: fmt.Sprintf("✅ **Zpráva ID %s byla schválena.**", msgID),
			Components: []discordgo.MessageComponent{},
		},
	})
}

func (a *AutoModService) handleReject(s *discordgo.Session, i *discordgo.InteractionCreate, msgID string) {
	key := fmt.Sprintf("automod:pending:%s", msgID)
	redis_client.Client.Del(redis_client.Ctx, key)

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Content: fmt.Sprintf("❌ **Zpráva ID %s byla zamítnuta.**", msgID),
			Components: []discordgo.MessageComponent{},
		},
	})
}

func (a *AutoModService) restoreMessage(s *discordgo.Session, data PendingMessage) {
	webhooks, _ := s.ChannelWebhooks(data.ChannelID)
	var webhook *discordgo.Webhook
	for _, wh := range webhooks {
		if wh.Name == "AutoMod Restorer" {
			webhook = wh
			break
		}
	}

	if webhook == nil {
		webhook, _ = s.WebhookCreate(data.ChannelID, "AutoMod Restorer", "")
	}

	if webhook != nil {
		s.WebhookExecute(webhook.ID, webhook.Token, true, &discordgo.WebhookParams{
			Content:   data.Content,
			Username:  data.AuthorName,
			AvatarURL: data.AuthorAvatar,
		})
	}
}
