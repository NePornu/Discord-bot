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
	GuildID          int64           `json:"guild_id"`
	RoleID           string          `json:"role_id"`
	ChannelID        string          `json:"channel_id"`
	Emojis           []string        `json:"emojis"`
	ReactOK          bool            `json:"react_ok"`
	ReplyOnSuccess   bool            `json:"reply_on_success"`
	SuccessMessages  []string        `json:"success_messages"`
	AllowExtraChars  bool            `json:"allow_extra_chars"`
	RequireAll       bool            `json:"require_all"`
	QuestPattern     string          `json:"quest_pattern"`
	Enabled          bool            `json:"enabled"`
	Milestones       map[int]string `json:"milestones"`
	SendDM           bool            `json:"send_dm"`
}

type UserStreak struct {
	Days           int      `json:"days"`
	LastUpdate     string   `json:"last_update"`
	CompletedDates []string `json:"completed_dates"`
}

type ChallengeService struct {
	Config  *config.Config
	Configs map[string]*ChallengeConfig
}

func NewChallengeService(cfg *config.Config) *ChallengeService {
	s := &ChallengeService{
		Config:  cfg,
		Configs: make(map[string]*ChallengeConfig),
	}
	s.LoadConfigs()
	return s
}

func (s *ChallengeService) LoadConfigs() {
	path := "data/challenge_config.json"
	if _, err := os.Stat("data"); os.IsNotExist(err) {
		os.Mkdir("data", 0755)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return
	}

	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		log.Printf("Error unmarshaling challenge config: %v", err)
		return
	}

	for k, v := range raw {
		vMap, ok := v.(map[string]interface{})
		if !ok {
			continue
		}

		cfg := &ChallengeConfig{}
		cfg.GuildID = s.toInt64(vMap["guild_id"])
		cfg.RoleID = s.toString(vMap["role_id"])
		cfg.ChannelID = s.toString(vMap["channel_id"])
		cfg.Emojis = s.toStringSlice(vMap["emojis"])
		cfg.ReactOK = s.toBool(vMap["react_ok"], true)
		cfg.ReplyOnSuccess = s.toBool(vMap["reply_on_success"], true)
		cfg.SuccessMessages = s.toStringSlice(vMap["success_messages"])
		cfg.QuestPattern = s.toString(vMap["quest_pattern"])
		cfg.Enabled = s.toBool(vMap["enabled"], true)
		cfg.SendDM = s.toBool(vMap["send_dm"], false)

		// Harder: Milestones map[int]string
		msRaw, _ := vMap["milestones"].(map[string]interface{})
		cfg.Milestones = make(map[int]string)
		for mk, mv := range msRaw {
			var mInt int
			fmt.Sscanf(mk, "%d", &mInt)
			cfg.Milestones[mInt] = s.toString(mv)
		}

		s.Configs[k] = cfg
	}
}

func (s *ChallengeService) SaveConfigs() {
	path := "data/challenge_config.json"
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

	cfg, exists := s.Configs[m.ChannelID]
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
		s.handleQuestSubmission(dg, m.GuildID, m.Author, cfg)
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

func (s *ChallengeService) handleQuestSubmission(dg *discordgo.Session, guildID string, user *discordgo.User, cfg *ChallengeConfig) {
	key := fmt.Sprintf("challenge:%s:default:streak:%s", guildID, user.ID)
	
	var streak UserStreak
	val, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err == nil {
		json.Unmarshal([]byte(val), &streak)
	}

	today := time.Now().Format("2006-01-02")
	for _, d := range streak.CompletedDates {
		if d == today { return } // Already done
	}

	yesterday := time.Now().AddDate(0, 0, -1).Format("2006-01-02")
	if streak.LastUpdate == yesterday || streak.LastUpdate == "" {
		streak.Days++
	} else {
		streak.Days = 1
		streak.CompletedDates = []string{}
	}

	streak.LastUpdate = today
	streak.CompletedDates = append(streak.CompletedDates, today)

	data, _ := json.Marshal(streak)
	redis_client.Client.Set(redis_client.Ctx, key, data, 0)

	// Milestones
	if roleID, ok := cfg.Milestones[streak.Days]; ok {
		dg.GuildMemberRoleAdd(guildID, user.ID, roleID)
		if cfg.SendDM {
			ch, err := dg.UserChannelCreate(user.ID)
			if err == nil {
				dg.ChannelMessageSend(ch.ID, fmt.Sprintf("🎉 Gratuluji! Dosáhl/a jsi **%d dní** ve výzvě!", streak.Days))
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
		user, _ := dg.User(r.UserID)
		if user != nil {
			s.handleQuestSubmission(dg, r.GuildID, user, cfg)
		}
	}
}

func (s *ChallengeService) HandleChallengeCommand(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	subcommand := options[0].Name

	switch subcommand {
	case "setup":
		s.handleSetup(dg, i)
	case "info":
		s.handleInfo(dg, i)
	}
}

func (s *ChallengeService) handleSetup(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	opts := i.ApplicationCommandData().Options[0].Options
	
	roleID := ""
	channelID := i.ChannelID
	emojisStr := ""

	for _, opt := range opts {
		switch opt.Name {
		case "role": roleID = opt.RoleValue(dg, i.GuildID).ID
		case "channel": channelID = opt.ChannelValue(dg).ID
		case "emojis": emojisStr = opt.StringValue()
		}
	}

	cfg := s.Configs[channelID]
	if cfg == nil {
		cfg = &ChallengeConfig{
			GuildID: s.toInt64(i.GuildID),
			ChannelID: channelID,
			Enabled: true,
			QuestPattern: "Quest —",
			SuccessMessages: []string{"Vítej ve výzvě! ✅", "Hotovo — jsi zapsán/a. 💪"},
		}
	}
	cfg.RoleID = roleID
	cfg.Emojis = strings.Fields(strings.ReplaceAll(emojisStr, ",", " "))
	s.Configs[channelID] = cfg
	s.SaveConfigs()

	dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: fmt.Sprintf("✅ Výzva nastavena pro <#%s>!", channelID),
			Flags: 64,
		},
	})
}

func (s *ChallengeService) handleInfo(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	cfg, exists := s.Configs[i.ChannelID]
	if !exists {
		dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: "❌ Žádná výzva v tomto kanále.", Flags: 64},
		})
		return
	}

	embed := &discordgo.MessageEmbed{
		Title: "📋 Výzva - konfigurace",
		Color: 0x3498db,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Role", Value: fmt.Sprintf("<@&%s>", cfg.RoleID), Inline: true},
			{Name: "Emojis", Value: strings.Join(cfg.Emojis, " "), Inline: true},
			{Name: "Pattern", Value: fmt.Sprintf("`%s`", cfg.QuestPattern), Inline: true},
		},
	}

	dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{Embeds: []*discordgo.MessageEmbed{embed}, Flags: 64},
	})
}
