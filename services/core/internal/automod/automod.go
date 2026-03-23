package automod

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

var linkRegex = regexp.MustCompile(`(?i)https?://[^\s/$.?#].[^\s]*`)

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

type AutoModSettings struct {
	LinkApprovalEnabled bool     `json:"link_approval_enabled"`
	ApprovalChannelID   string   `json:"approval_channel_id"`
	ExemptRoles         []string `json:"exempt_roles"`
	ExemptChannels      []string `json:"exempt_channels"`
	ExemptCategories    []string `json:"exempt_categories"`
}

type AutoModService struct {
	Config           *config.Config
	ApprovalChannel  string // Default fallback
}

func NewAutoModService(cfg *config.Config) *AutoModService {
	return &AutoModService{
		Config:          cfg,
		ApprovalChannel: cfg.PatternLogChannelID,
	}
}

func (a *AutoModService) GetSettings(guildID string) AutoModSettings {
	settings := AutoModSettings{
		LinkApprovalEnabled: true, // Default
		ApprovalChannelID:   a.Config.LinkApprovalChannel,
	}

	if redis_client.Client == nil {
		return settings
	}

	key := fmt.Sprintf("automod:settings:%s", guildID)
	val, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err == nil {
		json.Unmarshal([]byte(val), &settings)
	}
	return settings
}

func (a *AutoModService) SaveSettings(guildID string, settings AutoModSettings) {
	if redis_client.Client == nil {
		return
	}
	key := fmt.Sprintf("automod:settings:%s", guildID)
	data, _ := json.Marshal(settings)
	redis_client.Client.Set(redis_client.Ctx, key, data, 0)
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
	
	settings := a.GetSettings(m.GuildID)

	// 1. Link Approval (Priority if enabled)
	if settings.LinkApprovalEnabled {
		if a.ProcessLinkApproval(s, m.Message, settings) {
			return
		}
	}

	// 2. Regex Filters
	a.ProcessAutoMod(s, m.Message, settings)
}

func (a *AutoModService) OnMessageUpdate(s *discordgo.Session, m *discordgo.MessageUpdate) {
	if m.Author == nil || m.Author.Bot || m.GuildID == "" {
		return
	}

	settings := a.GetSettings(m.GuildID)

	// 1. Link Approval (Priority if enabled)
	if settings.LinkApprovalEnabled {
		if a.ProcessLinkApproval(s, m.Message, settings) {
			return
		}
	}

	// 2. Regex Filters
	a.ProcessAutoMod(s, m.Message, settings)
}

func (a *AutoModService) ProcessAutoMod(s *discordgo.Session, m *discordgo.Message, settings AutoModSettings) bool {
	// 0. Global Exemption Check
	if a.isExempt(s, m, Filter{}, settings) {
		return false
	}
	filters, _ := a.GetFilters(m.GuildID)
	if len(filters) == 0 {
		return false
	}

	for _, f := range filters {
		re, err := regexp.Compile("(?i)" + f.Pattern)
		if err != nil {
			continue
		}

		if re.MatchString(m.Content) {
			// Check exemptions
			if a.isExempt(s, m, f, settings) {
				continue
			}

			// Match found!
			a.HandleViolation(s, m, f, settings)
			return true
		}
	}
	return false
}

func (a *AutoModService) isExempt(s *discordgo.Session, m *discordgo.Message, f Filter, settings AutoModSettings) bool {
	// 1. GLOBAL Exemptions (from .env and Redis)
	if a.isLinkExempt(s, m, settings) {
		return true
	}

	// 2. Per-Filter Channel exemption
	for _, cid := range f.AllowedChannels {
		if cid == m.ChannelID {
			return true
		}
	}

	// 3. Per-Filter Role exemption
	if m.Member != nil {
		for _, rid := range f.AllowedRoles {
			for _, userRid := range m.Member.Roles {
				if rid == userRid {
					return true
				}
			}
		}
	}

	// 4. Whitelist: if message contains a whitelisted term, exempt it
	for _, w := range f.Whitelist {
		if strings.Contains(strings.ToLower(m.Content), strings.ToLower(w)) {
			return true
		}
	}

	return false
}

func (a *AutoModService) HandleViolation(s *discordgo.Session, m *discordgo.Message, f Filter, settings AutoModSettings) {
	// 1. Delete message
	s.ChannelMessageDelete(m.ChannelID, m.ID)

	// 2. Handle Action
	if f.Action == "auto_reject" {
		a.logViolation(s, m, "Auto-Rejected")
		return
	}

	// 3. Action is "approve"
	a.queueForApproval(s, m, settings)
}

func (a *AutoModService) queueForApproval(s *discordgo.Session, m *discordgo.Message, settings AutoModSettings) {
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

	// Determine destination channel (Always use LinkApprovalChannel as requested)
	targetChannel := settings.ApprovalChannelID
	if targetChannel == "" {
		targetChannel = a.ApprovalChannel // Fallback to Pattern Log if Link channel is not set
	}

	if targetChannel == "" {
		return
	}

	title := "🛡️ AutoMod: Message Awaiting Approval"
	color := 0xffa500 // Orange
	if linkRegex.MatchString(m.Content) {
		title = "🔗 Odkaz ke schválení (AutoMod)"
		color = 0x3498DB // Blue
	}

	embed := &discordgo.MessageEmbed{
		Title:       title,
		Description: m.Content,
		Color:       int(color),
		Author: &discordgo.MessageEmbedAuthor{
			Name:    fmt.Sprintf("%s (%s)", m.Author.Username, m.Author.ID),
			IconURL: m.Author.AvatarURL(""),
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Message ID: %s | Channel: %s", m.ID, m.ChannelID),
		},
	}

	btnApprove := discordgo.Button{
		Label:    "Schválit",
		Style:    discordgo.SuccessButton,
		CustomID: "automod_approve:" + m.ID,
	}
	btnReject := discordgo.Button{
		Label:    "Zamítnout",
		Style:    discordgo.DangerButton,
		CustomID: "automod_reject:" + m.ID,
	}

	s.ChannelMessageSendComplex(targetChannel, &discordgo.MessageSend{
		Embeds: []*discordgo.MessageEmbed{embed},
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{btnApprove, btnReject},
			},
		},
	})
}

func (a *AutoModService) ProcessLinkApproval(s *discordgo.Session, m *discordgo.Message, settings AutoModSettings) bool {
	if !linkRegex.MatchString(m.Content) {
		return false
	}

	if a.isLinkExempt(s, m, settings) {
		return false
	}

	// Delete original message
	s.ChannelMessageDelete(m.ChannelID, m.ID)

	// Queue for approval
	a.queueLinkForApproval(s, m, settings)
	return true
}
func (a *AutoModService) isLinkExempt(s *discordgo.Session, m *discordgo.Message, settings AutoModSettings) bool {
	// 1. Roles (Merged .env + Redis)
	if m.Member != nil {
		allExemptRoles := append(a.Config.LinkExemptRoles, settings.ExemptRoles...)
		for _, roleID := range m.Member.Roles {
			for _, exemptRole := range allExemptRoles {
				if roleID == exemptRole {
					return true
				}
			}
		}
	}

	// 2. Channels (Merged .env + Redis)
	allExemptChannels := append(a.Config.LinkExemptChannels, settings.ExemptChannels...)
	for _, channelID := range allExemptChannels {
		if m.ChannelID == channelID {
			return true
		}
	}

	// 3. Categories (Redis only)
	if len(settings.ExemptCategories) > 0 {
		ch, err := s.State.Channel(m.ChannelID)
		if err == nil && ch.ParentID != "" {
			for _, catID := range settings.ExemptCategories {
				if ch.ParentID == catID {
					return true
				}
			}
		}
	}

	return false
}

func (a *AutoModService) queueLinkForApproval(s *discordgo.Session, m *discordgo.Message, settings AutoModSettings) {
	msgData := PendingMessage{
		Content:      m.Content,
		AuthorID:     m.Author.ID,
		AuthorName:   m.Author.Username,
		AuthorAvatar: m.Author.AvatarURL(""),
		ChannelID:    m.ChannelID,
		GuildID:      m.GuildID,
	}
	data, _ := json.Marshal(msgData)
	key := fmt.Sprintf("automod:pending_link:%s", m.ID)
	if redis_client.Client != nil {
		redis_client.Client.Set(redis_client.Ctx, key, data, 24*time.Hour)
	}

	embed := &discordgo.MessageEmbed{
		Title:       "🔗 Odkaz ke schválení",
		Description: fmt.Sprintf("**Autor:** %s\n**Kanál:** <#%s>\n\n**Obsah:**\n%s", m.Author.Mention(), m.ChannelID, m.Content),
		Color:       0x3498DB,
		Timestamp:   time.Now().Format(time.RFC3339),
	}

	targetChannel := settings.ApprovalChannelID
	if targetChannel == "" {
		targetChannel = a.ApprovalChannel
	}

	if targetChannel == "" {
		return
	}

	_, err := s.ChannelMessageSendComplex(targetChannel, &discordgo.MessageSend{
		Embeds: []*discordgo.MessageEmbed{embed},
		Components: []discordgo.MessageComponent{
			discordgo.ActionsRow{
				Components: []discordgo.MessageComponent{
					discordgo.Button{
						Label:    "Schválit (Vrátit)",
						Style:    discordgo.SuccessButton,
						CustomID: fmt.Sprintf("link_approve:%s", m.ID),
					},
					discordgo.Button{
						Label:    "Zamítnout",
						Style:    discordgo.DangerButton,
						CustomID: fmt.Sprintf("link_reject:%s", m.ID),
					},
				},
			},
		},
	})

	if err != nil {
		slog.Error("Failed to send link approval request", "error", err)
	}
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
	case "link-toggle":
		a.handleLinkToggle(s, i)
	case "link-channel":
		a.handleLinkChannel(s, i)
	case "exempt-add":
		a.handleExemptAdd(s, i)
	case "exempt-remove":
		a.handleExemptRemove(s, i)
	case "exempt-list":
		a.handleExemptList(s, i)
	case "status":
		a.handleStatus(s, i)
	}
}

func (a *AutoModService) handleLinkToggle(s *discordgo.Session, i *discordgo.InteractionCreate) {
	enabled := i.ApplicationCommandData().Options[0].Options[0].BoolValue()
	settings := a.GetSettings(i.GuildID)
	settings.LinkApprovalEnabled = enabled
	a.SaveSettings(i.GuildID, settings)

	status := "vypnuto"
	if enabled {
		status = "zapnuto"
	}
	content := fmt.Sprintf("✅ Schvalování odkazů bylo **%s**.", status)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}

func (a *AutoModService) handleLinkChannel(s *discordgo.Session, i *discordgo.InteractionCreate) {
	channel := i.ApplicationCommandData().Options[0].Options[0].ChannelValue(s)
	settings := a.GetSettings(i.GuildID)
	settings.ApprovalChannelID = channel.ID
	a.SaveSettings(i.GuildID, settings)

	content := fmt.Sprintf("✅ Kanál pro schvalování odkazů nastaven na <#%s>.", channel.ID)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
}

func (a *AutoModService) handleStatus(s *discordgo.Session, i *discordgo.InteractionCreate) {
	settings := a.GetSettings(i.GuildID)
	filters, _ := a.GetFilters(i.GuildID)

	linkStatus := "🔴 Vypnuto"
	if settings.LinkApprovalEnabled {
		linkStatus = "🟢 Zapnuto"
	}

	approvalChannel := "Není nastaven"
	if settings.ApprovalChannelID != "" {
		approvalChannel = fmt.Sprintf("<#%s>", settings.ApprovalChannelID)
	}

	embed := &discordgo.MessageEmbed{
		Title: "🛡️ Stav AutoMod systému",
		Color: 0x3498DB,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Schvalování odkazů", Value: linkStatus, Inline: true},
			{Name: "Kanál pro schvalování", Value: approvalChannel, Inline: true},
			{Name: "Regex filtry", Value: fmt.Sprintf("%d", len(filters)), Inline: true},
			{Name: "Výjimky (Role/Kanály/Kat.)", Value: fmt.Sprintf("%d / %d / %d", len(settings.ExemptRoles), len(settings.ExemptChannels), len(settings.ExemptCategories)), Inline: true},
		},
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func (a *AutoModService) handleExemptAdd(s *discordgo.Session, i *discordgo.InteractionCreate) {
	opts := i.ApplicationCommandData().Options[0].Options
	settings := a.GetSettings(i.GuildID)
	
	msg := ""
	for _, opt := range opts {
		switch opt.Name {
		case "role":
			role := opt.RoleValue(s, i.GuildID)
			settings.ExemptRoles = append(settings.ExemptRoles, role.ID)
			msg = fmt.Sprintf("✅ Role **%s** přidána do výjimek.", role.Name)
		case "kanal":
			channel := opt.ChannelValue(s)
			settings.ExemptChannels = append(settings.ExemptChannels, channel.ID)
			msg = fmt.Sprintf("✅ Kanál <#%s> přidán do výjimek.", channel.ID)
		case "kategorie":
			channel := opt.ChannelValue(s)
			if channel.Type != discordgo.ChannelTypeGuildCategory {
				msg = "❌ Vybraný kanál není kategorie."
			} else {
				settings.ExemptCategories = append(settings.ExemptCategories, channel.ID)
				msg = fmt.Sprintf("✅ Kategorie **%s** přidána do výjimek.", channel.Name)
			}
		}
	}
	
	a.SaveSettings(i.GuildID, settings)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &msg})
}

func (a *AutoModService) handleExemptRemove(s *discordgo.Session, i *discordgo.InteractionCreate) {
	opts := i.ApplicationCommandData().Options[0].Options
	settings := a.GetSettings(i.GuildID)
	
	msg := ""
	for _, opt := range opts {
		val := opt.StringValue()
		found := false
		
		// Helper to remove from string slice
		remove := func(slice []string, val string) ([]string, bool) {
			for idx, item := range slice {
				if item == val {
					return append(slice[:idx], slice[idx+1:]...), true
				}
			}
			return slice, false
		}

		switch opt.Name {
		case "role":
			settings.ExemptRoles, found = remove(settings.ExemptRoles, val)
			msg = "✅ Role odebrána z výjimek."
		case "kanal":
			settings.ExemptChannels, found = remove(settings.ExemptChannels, val)
			msg = "✅ Kanál odebrán z výjimek."
		case "kategorie":
			settings.ExemptCategories, found = remove(settings.ExemptCategories, val)
			msg = "✅ Kategorie odebrána z výjimek."
		}
		
		if !found {
			msg = "❌ Tato položka nebyla v seznamu výjimek nalezena."
		}
	}
	
	a.SaveSettings(i.GuildID, settings)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &msg})
}

func (a *AutoModService) handleExemptList(s *discordgo.Session, i *discordgo.InteractionCreate) {
	settings := a.GetSettings(i.GuildID)
	
	roles := "Žádné"
	if len(settings.ExemptRoles) > 0 {
		roles = ""
		for _, rid := range settings.ExemptRoles {
			roles += fmt.Sprintf("<@&%s> ", rid)
		}
	}
	
	channels := "Žádné"
	if len(settings.ExemptChannels) > 0 {
		channels = ""
		for _, cid := range settings.ExemptChannels {
			channels += fmt.Sprintf("<#%s> ", cid)
		}
	}
	
	categories := "Žádné"
	if len(settings.ExemptCategories) > 0 {
		categories = ""
		for _, cid := range settings.ExemptCategories {
			categories += fmt.Sprintf("<#%s> ", cid)
		}
	}
	
	embed := &discordgo.MessageEmbed{
		Title: "🛡️ Seznam výjimek AutoModu",
		Color: 0x3498DB,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Ignorované Role", Value: roles, Inline: false},
			{Name: "Ignorované Kanály", Value: channels, Inline: false},
			{Name: "Ignorované Kategorie", Value: categories, Inline: false},
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: "Položky z .env souboru zde nejsou zobrazeny, ale jsou také ignorovány.",
		},
	}
	
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Embeds: &[]*discordgo.MessageEmbed{embed}})
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
	
	if strings.HasPrefix(customID, "automod_approve:") || strings.HasPrefix(customID, "link_approve:") {
		msgID := ""
		if strings.HasPrefix(customID, "automod_approve:") {
			msgID = strings.TrimPrefix(customID, "automod_approve:")
		} else {
			msgID = strings.TrimPrefix(customID, "link_approve:")
		}
		a.handleApprove(s, i, msgID)
		return
	}
	
	if strings.HasPrefix(customID, "automod_reject:") || strings.HasPrefix(customID, "link_reject:") {
		msgID := ""
		if strings.HasPrefix(customID, "automod_reject:") {
			msgID = strings.TrimPrefix(customID, "automod_reject:")
		} else {
			msgID = strings.TrimPrefix(customID, "link_reject:")
		}
		a.handleReject(s, i, msgID)
		return
	}
}

func (a *AutoModService) handleApprove(s *discordgo.Session, i *discordgo.InteractionCreate, msgID string) {
	// Try both keys
	keys := []string{
		fmt.Sprintf("automod:pending:%s", msgID),
		fmt.Sprintf("automod:pending_link:%s", msgID),
	}

	var val string
	var err error
	foundKey := ""

	for _, k := range keys {
		val, err = redis_client.Client.Get(redis_client.Ctx, k).Result()
		if err == nil {
			foundKey = k
			break
		}
	}

	if foundKey == "" {
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

	modName := i.Member.User.Username
	if i.Member.Nick != "" {
		modName = i.Member.Nick
	}

	embed := &discordgo.MessageEmbed{
		Author: &discordgo.MessageEmbedAuthor{
			Name:    fmt.Sprintf("%s (%s)", data.AuthorName, data.AuthorID),
			IconURL: data.AuthorAvatar,
		},
		Title:       "✅ Message Approved",
		Description: data.Content,
		Color:       0x2ECC71, // Green
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Channel", Value: fmt.Sprintf("<#%s>", data.ChannelID), Inline: true},
			{Name: "Approved by", Value: fmt.Sprintf("%s • %s", modName, time.Now().Format("02.01.06 15:04")), Inline: true},
		},
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Embeds: []*discordgo.MessageEmbed{embed},
			Components: []discordgo.MessageComponent{},
		},
	})
	
	for _, k := range keys {
		redis_client.Client.Del(redis_client.Ctx, k)
	}

	// Auto-delete after 1 minute
	time.AfterFunc(1*time.Minute, func() {
		s.InteractionResponseDelete(i.Interaction)
	})
}

func (a *AutoModService) handleReject(s *discordgo.Session, i *discordgo.InteractionCreate, msgID string) {
	keys := []string{
		fmt.Sprintf("automod:pending:%s", msgID),
		fmt.Sprintf("automod:pending_link:%s", msgID),
	}
	
	for _, k := range keys {
		redis_client.Client.Del(redis_client.Ctx, k)
	}

	modName := i.Member.User.Username
	if i.Member.Nick != "" {
		modName = i.Member.Nick
	}

	embed := &discordgo.MessageEmbed{
		Title:       "❌ Message Rejected",
		Description: fmt.Sprintf("ID: %s\nRejected by: %s", msgID, modName),
		Color:       0xE74C3C, // Red
		Timestamp:   time.Now().Format(time.RFC3339),
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseUpdateMessage,
		Data: &discordgo.InteractionResponseData{
			Embeds:     []*discordgo.MessageEmbed{embed},
			Components: []discordgo.MessageComponent{},
		},
	})

	// Auto-delete after 1 minute
	time.AfterFunc(1*time.Minute, func() {
		s.InteractionResponseDelete(i.Interaction)
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
