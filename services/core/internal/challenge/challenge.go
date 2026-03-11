package challenge

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"os"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type ChallengeConfig struct {
	ID               string          `json:"id"`
	GuildID          int64           `json:"guild_id"`
	RoleID           string          `json:"role_id"`
	ChannelIDs       []string        `json:"channel_ids"`
	Emojis           []string        `json:"emojis"`
	ReactOK          bool            `json:"react_ok"`
	ReplyOnSuccess   bool            `json:"reply_on_success"`
	SuccessMessages  []string        `json:"success_messages"`
	AllowExtraChars  bool            `json:"allow_extra_chars"`
	RequireAll       bool            `json:"require_all"`
	QuestPattern     string          `json:"quest_pattern"`
	Enabled          bool            `json:"enabled"`
	Milestones       map[int]string  `json:"milestones"`
	SendDM           bool            `json:"send_dm"`
	StartDate        string          `json:"start_date"` // YYYYMMDD
	EndDate          string          `json:"end_date"`   // YYYYMMDD
}

type UserStreak struct {
	Days           int      `json:"days"`
	LastUpdate     string   `json:"last_update"`
	CompletedDates []string `json:"completed_dates"`
}

type ChallengeService struct {
	Config          *config.Config
	Configs         map[string]*ChallengeConfig // Map: ChallengeID -> Config
	ChannelToConfig map[string]*ChallengeConfig // Map: ChannelID -> Config (cached)
}

func NewChallengeService(cfg *config.Config) *ChallengeService {
	s := &ChallengeService{
		Config:          cfg,
		Configs:         make(map[string]*ChallengeConfig),
		ChannelToConfig: make(map[string]*ChallengeConfig),
	}
	s.LoadConfigs()
	return s
}

func (s *ChallengeService) LoadConfigs() {
	path := "data/challenges.json"
	
	// Ensure data directory exists
	if _, err := os.Stat("data"); os.IsNotExist(err) {
		os.Mkdir("data", 0755)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		log.Printf("Challenge config file %s not found. Using empty config.", path)
		return
	}

	if err := json.Unmarshal(data, &s.Configs); err != nil {
		log.Printf("Error unmarshaling challenges.json: %v", err)
		return
	}

	// Build the channel lookup cache
	s.ChannelToConfig = make(map[string]*ChallengeConfig)
	for id, cfg := range s.Configs {
		cfg.ID = id
		for _, chID := range cfg.ChannelIDs {
			s.ChannelToConfig[chID] = cfg
		}
	}
}

func (s *ChallengeService) SaveConfigs() {
	path := "data/challenges.json"
	data, _ := json.MarshalIndent(s.Configs, "", "  ")
	os.WriteFile(path, data, 0644)
}

// Helpers for unmarshaling loose JSON
func (s *ChallengeService) toInt64(v interface{}) int64 {
	switch val := v.(type) {
	case float64: return int64(val)
	case string:
		var i int64
		fmt.Sscanf(val, "%d", &i)
		return i
	}
	return 0
}
func (s *ChallengeService) toString(v interface{}) string {
	if v == nil { return "" }
	return fmt.Sprintf("%v", v)
}
func (s *ChallengeService) toBool(v interface{}, def bool) bool {
	if v == nil { return def }
	b, ok := v.(bool)
	if !ok { return def }
	return b
}
func (s *ChallengeService) toStringSlice(v interface{}) []string {
	res := []string{}
	if v == nil { return res }
	slice, ok := v.([]interface{})
	if !ok { return res }
	for _, item := range slice {
		res = append(res, fmt.Sprintf("%v", item))
	}
	return res
}

func (s *ChallengeService) OnMessage(dg *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID == "" {
		return
	}

	cfg, exists := s.ChannelToConfig[m.ChannelID]
	if !exists || !cfg.Enabled {
		return
	}

	// 1. Emoji-role check
	if len(cfg.Emojis) > 0 {
		content := strings.TrimSpace(m.Content)
		hit := s.messageContainsTargets(content, cfg.Emojis, cfg.RequireAll)
		if hit {
			if cfg.ReactOK {
				dg.MessageReactionAdd(m.ChannelID, m.ID, "✅")
			}
			s.assignRoleImmediate(dg, m.GuildID, m.Author.ID, cfg, m.Message)
			return
		}
	}

	// 2. Quest pattern check
	pattern := cfg.QuestPattern
	if pattern == "" { pattern = "Quest —" }
	if strings.HasPrefix(pattern, ".") || strings.HasPrefix(pattern, ":") {
		return // Emoji reaction quest handled in OnReactionAdd
	}

	if s.matchesTextPattern(m.Content, pattern) {
		s.handleQuestSubmission(dg, m.GuildID, m.Author, cfg, m.Message)
	}
}

func (s *ChallengeService) messageContainsTargets(content string, targets []string, requireAll bool) bool {
	contentNorm := strings.ReplaceAll(content, "\ufe0f", "")
	hits := 0
	for _, t := range targets {
		tNorm := strings.ReplaceAll(t, "\ufe0f", "")
		if strings.Contains(contentNorm, tNorm) {
			hits++
			if !requireAll { return true }
		}
	}
	if requireAll && hits == len(targets) { return true }
	return false
}

func (s *ChallengeService) matchesTextPattern(content, pattern string) bool {
	contentLower := strings.ToLower(content)
	patternLower := strings.ToLower(pattern)
	
	if strings.Contains(content, "✅") && strings.Contains(contentLower, patternLower) {
		return true
	}
	if strings.Contains(contentLower, patternLower) {
		return true
	}
	return false
}

func (s *ChallengeService) assignRoleImmediate(dg *discordgo.Session, guildID, userID string, cfg *ChallengeConfig, m *discordgo.Message) {
	if cfg.RoleID == "" { return }
	
	err := dg.GuildMemberRoleAdd(guildID, userID, cfg.RoleID)
	if err == nil && cfg.ReplyOnSuccess && len(cfg.SuccessMessages) > 0 {
		msg := cfg.SuccessMessages[rand.Intn(len(cfg.SuccessMessages))]
		dg.ChannelMessageSendReply(m.ChannelID, msg, m.Reference())
	}
}

func (s *ChallengeService) handleQuestSubmission(dg *discordgo.Session, guildID string, user *discordgo.User, cfg *ChallengeConfig, m *discordgo.Message) {
	today := time.Now().Format("20060102")
	
	// Date range check
	if cfg.StartDate != "" && today < cfg.StartDate {
		return
	}
	if cfg.EndDate != "" && today > cfg.EndDate {
		return
	}

	key := fmt.Sprintf("challenge:streak:%s:%s:%s", guildID, cfg.ID, user.ID)
	
	var streak UserStreak
	val, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err == nil {
		json.Unmarshal([]byte(val), &streak)
	}

	// Double entry check for today
	for _, d := range streak.CompletedDates {
		if d == today {
			return
		}
	}

	yesterday := time.Now().AddDate(0, 0, -1).Format("20060102")
	if streak.LastUpdate == yesterday || streak.LastUpdate == "" {
		streak.Days++
	} else {
		streak.Days = 1
	}

	streak.LastUpdate = today
	streak.CompletedDates = append(streak.CompletedDates, today)

	data, _ := json.Marshal(streak)
	redis_client.Client.Set(redis_client.Ctx, key, data, 0)

	// Feedback reaction
	dg.MessageReactionAdd(m.ChannelID, m.ID, "✅")

	// Milestones
	if roleID, ok := cfg.Milestones[streak.Days]; ok {
		dg.GuildMemberRoleAdd(guildID, user.ID, roleID)
		
		// Universal success message with mention
		successMsg := fmt.Sprintf("🔥 Gratulace <@%s>! Dosáhl/a jsi **%d dní** a získáváš novou roli! 👑", user.ID, streak.Days)
		dg.ChannelMessageSend(m.ChannelID, successMsg)

		if cfg.SendDM {
			ch, err := dg.UserChannelCreate(user.ID)
			if err == nil {
				dg.ChannelMessageSend(ch.ID, fmt.Sprintf("🎉 Gratuluji! Dosáhl/a jsi **%d dní** ve výzvě %s!", streak.Days, cfg.ID))
			}
		}
	}
}

func (s *ChallengeService) OnReactionAdd(dg *discordgo.Session, r *discordgo.MessageReactionAdd) {
	if r.UserID == dg.State.User.ID { return }

	cfg, exists := s.Configs[r.ChannelID]
	if !exists || !cfg.Enabled { return }

	pattern := cfg.QuestPattern
	if !strings.HasPrefix(pattern, ".") && !strings.HasPrefix(pattern, ":") {
		return
	}

	expected := strings.TrimLeft(pattern, ".: ")
	if r.Emoji.Name == expected || r.Emoji.APIName() == expected {
		msg, _ := dg.ChannelMessage(r.ChannelID, r.MessageID)
		if msg != nil {
			s.handleQuestSubmission(dg, r.GuildID, msg.Author, cfg, msg)
		}
	}
}

func (s *ChallengeService) HandleChallengeCommand(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: 64, // Ephemeral
		},
	})

	options := i.ApplicationCommandData().Options
	subcommand := options[0].Name

	switch subcommand {
	case "setup":
		s.handleSetup(dg, i)
	case "milestone":
		s.handleMilestone(dg, i)
	case "info":
		s.handleInfo(dg, i)
	case "stats":
		s.handleStats(dg, i)
	case "backfill":
		s.handleBackfill(dg, i)
	}
}

func (s *ChallengeService) handleSetup(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	opts := i.ApplicationCommandData().Options[0].Options
	
	id := ""
	channelID := i.ChannelID
	pattern := ""
	start := ""
	end := ""

	for _, opt := range opts {
		switch opt.Name {
		case "id": id = opt.StringValue()
		case "pattern": pattern = opt.StringValue()
		case "channel": channelID = opt.ChannelValue(dg).ID
		case "start": start = opt.StringValue()
		case "end": end = opt.StringValue()
		}
	}

	cfg := s.Configs[id]
	if cfg == nil {
		cfg = &ChallengeConfig{
			ID: id,
			GuildID: s.toInt64(i.GuildID),
			Enabled: true,
			Milestones: make(map[int]string),
		}
	}

	if pattern != "" { cfg.QuestPattern = pattern }
	if start != "" { cfg.StartDate = start }
	if end != "" { cfg.EndDate = end }
	
	// Add channel if not already there
	found := false
	for _, ch := range cfg.ChannelIDs {
		if ch == channelID { found = true; break }
	}
	if !found {
		cfg.ChannelIDs = append(cfg.ChannelIDs, channelID)
	}

	s.Configs[id] = cfg
	s.SaveConfigs()
	s.LoadConfigs() // Refresh cache

	content := fmt.Sprintf("✅ Výzva **%s** byla nastavena/upravena!", id)
	dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}

func (s *ChallengeService) handleMilestone(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	opts := i.ApplicationCommandData().Options[0].Options
	
	id := ""
	days := 0
	roleID := ""

	for _, opt := range opts {
		switch opt.Name {
		case "id": id = opt.StringValue()
		case "days": days = int(opt.IntValue())
		case "role": roleID = opt.RoleValue(dg, i.GuildID).ID
		}
	}

	cfg := s.Configs[id]
	if cfg == nil {
		content := fmt.Sprintf("❌ Výzva **%s** neexistuje. Nejdříve ji vytvoř příkazem `/challenge setup`.", id)
		dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	if cfg.Milestones == nil {
		cfg.Milestones = make(map[int]string)
	}
	cfg.Milestones[days] = roleID

	s.Configs[id] = cfg
	s.SaveConfigs()

	content := fmt.Sprintf("✅ Milník **%d dní** s rolí <@&%s> byl přidán k výzvě **%s**!", days, roleID, id)
	dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}

func (s *ChallengeService) handleInfo(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	var cfg *ChallengeConfig
	
	opts := i.ApplicationCommandData().Options[0].Options
	if len(opts) > 0 && opts[0].Name == "id" {
		cfg = s.Configs[opts[0].StringValue()]
	} else {
		cfg = s.ChannelToConfig[i.ChannelID]
	}

	if cfg == nil {
		content := "❌ Žádná výzva nenalezena."
		dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	mList := []string{}
	for d, r := range cfg.Milestones {
		mList = append(mList, fmt.Sprintf("- **%d dní**: <@&%s>", d, r))
	}
	if len(mList) == 0 { mList = append(mList, "_Žádné milníky_") }

	embed := &discordgo.MessageEmbed{
		Title: fmt.Sprintf("📋 Výzva: %s", cfg.ID),
		Color: 0x3498db,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Vzor", Value: fmt.Sprintf("`%s`", cfg.QuestPattern), Inline: true},
			{Name: "Kanály", Value: strings.Join(cfg.ChannelIDs, ", "), Inline: true},
			{Name: "Období", Value: fmt.Sprintf("%s - %s", cfg.StartDate, cfg.EndDate), Inline: true},
			{Name: "Milníky", Value: strings.Join(mList, "\n"), Inline: false},
		},
	}

	dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func (s *ChallengeService) handleStats(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	user := i.Member.User
	if user == nil && i.User != nil {
		user = i.User
	}

	cfg, exists := s.ChannelToConfig[i.ChannelID]
	if !exists {
		content := "❌ V tomto kanále neběží žádná výzva."
		dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: content, Flags: 64},
		})
		return
	}

	key := fmt.Sprintf("challenge:streak:%s:%s:%s", i.GuildID, cfg.ID, user.ID)
	var streak UserStreak
	val, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err == nil {
		json.Unmarshal([]byte(val), &streak)
	}

	embed := &discordgo.MessageEmbed{
		Title: fmt.Sprintf("📊 Výzva: %s — %s", cfg.ID, user.Username),
		Color: 0x3498db,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Dnů splněno", Value: fmt.Sprintf("🔥 **%d**", streak.Days), Inline: true},
			{Name: "Poslední záznam", Value: streak.LastUpdate, Inline: true},
		},
	}

	// Calculate next milestone
	var milestones []int
	for m := range cfg.Milestones {
		milestones = append(milestones, m)
	}
	// Sort milestones (naively)
	for i := 0; i < len(milestones); i++ {
		for j := i + 1; j < len(milestones); j++ {
			if milestones[i] > milestones[j] {
				milestones[i], milestones[j] = milestones[j], milestones[i]
			}
		}
	}

	nextM := 0
	for _, m := range milestones {
		if m > streak.Days {
			nextM = m
			break
		}
	}

	if nextM > 0 {
		embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
			Name: "Další milník", Value: fmt.Sprintf("%d dní (zbývá %d)", nextM, nextM-streak.Days), Inline: false,
		})
	} else if len(milestones) > 0 {
		embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
			Name: "Status", Value: "👑 Všechny milníky splněny!", Inline: false,
		})
	}

	dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func (s *ChallengeService) handleBackfill(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	// Only accessible if subcommand "backfill" exists in slash command definition
	cfg, exists := s.ChannelToConfig[i.ChannelID]
	if !exists {
		content := "❌ V tomto kanále neběží žádná výzva."
		dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	content := fmt.Sprintf("⏳ Spouštím backfill pro výzvu **%s** v <#%s>...", cfg.ID, i.ChannelID)
	dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})

	count := 0
	beforeID := ""
	limit := 100 
	
	// Track roles given during this session
	type userReport struct {
		Username string
		Roles    []string
	}
	report := make(map[string]*userReport)

	for {
		msgs, err := dg.ChannelMessages(i.ChannelID, limit, beforeID, "", "")
		if err != nil || len(msgs) == 0 {
			break
		}

		for _, msg := range msgs {
			beforeID = msg.ID
			if msg.Author.Bot {
				continue
			}

			if s.matchesTextPattern(msg.Content, cfg.QuestPattern) {
				day := msg.Timestamp.Format("20060102")
				
				// Date check
				if (cfg.StartDate != "" && day < cfg.StartDate) || (cfg.EndDate != "" && day > cfg.EndDate) {
					continue
				}

				// Logic similar to handleQuestSubmission but without immediate rewards (to avoid duplicate role pings)
				key := fmt.Sprintf("challenge:streak:%s:%s:%s", i.GuildID, cfg.ID, msg.Author.ID)
				var streak UserStreak
				val, _ := redis_client.Client.Get(redis_client.Ctx, key).Result()
				json.Unmarshal([]byte(val), &streak)

				alreadyExists := false
				for _, d := range streak.CompletedDates {
					if d == day {
						alreadyExists = true
						break
					}
				}

				if !alreadyExists {
					streak.CompletedDates = append(streak.CompletedDates, day)
					streak.Days = len(streak.CompletedDates)
					
					if day > streak.LastUpdate {
						streak.LastUpdate = day
					}

					data, _ := json.Marshal(streak)
					redis_client.Client.Set(redis_client.Ctx, key, data, 0)
					count++
				}

				// Always check milestones during backfill to sync roles
				for mDays, roleID := range cfg.Milestones {
					if streak.Days >= mDays {
						// Check if they already have the role to avoid redundant API calls
						hasRole := false
						member, err := dg.GuildMember(i.GuildID, msg.Author.ID)
						if err == nil {
							for _, rID := range member.Roles {
								if rID == roleID { hasRole = true; break }
							}
						}

						if !hasRole {
							dg.GuildMemberRoleAdd(i.GuildID, msg.Author.ID, roleID)
							if report[msg.Author.ID] == nil {
								report[msg.Author.ID] = &userReport{Username: msg.Author.Username}
							}
							
							// Avoid duplicates in report
							alreadyReported := false
							for _, r := range report[msg.Author.ID].Roles {
								if r == roleID { alreadyReported = true; break }
							}
							if !alreadyReported {
								report[msg.Author.ID].Roles = append(report[msg.Author.ID].Roles, roleID)
							}
						}
					}
				}
			}
		}

		if len(msgs) < limit {
			break
		}
		time.Sleep(500 * time.Millisecond) // Rate limit safety
	}

	finalContent := fmt.Sprintf("✅ Backfill dokončen! Zpracováno **%d** nových questů pro výzvu **%s**.\n\n", count, cfg.ID)
	
	if len(report) > 0 {
		finalContent += "**Předané role:**\n"
		for userID, r := range report {
			roleMentions := []string{}
			for _, rID := range r.Roles {
				roleMentions = append(roleMentions, fmt.Sprintf("<@&%s>", rID))
			}
			finalContent += fmt.Sprintf("- **%s**: %s\n", r.Username, strings.Join(roleMentions, ", "))
			
			// Optional: Congratulate in channel
			dg.ChannelMessageSend(i.ChannelID, fmt.Sprintf("🔥 **Zpětné vyhodnocení:** <@%s> získává role: %s! Gratulujeme! 👑", userID, strings.Join(roleMentions, ", ")))
		}
	} else {
		finalContent += "_Žádné nové role nebyly přiděleny (všichni již mají správné role)._"
	}

	dg.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &finalContent})
}
