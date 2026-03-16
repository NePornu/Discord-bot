package reputation

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type ReputationService struct {
	Config *config.Config
}

func NewReputationService(cfg *config.Config) *ReputationService {
	return &ReputationService{Config: cfg}
}

const (
	MaxDailyRep = 3
)

type RepEvent struct {
	GiverID   string `json:"giver_id"`
	Reason    string `json:"reason"`
	Timestamp int64  `json:"ts"`
	ChannelID string `json:"channel_id"`
}

func (r *ReputationService) GiveRep(fromID, toID, guildID, channelID, reason string) (int, error) {
	if fromID == toID {
		return 0, fmt.Errorf("nemůžeš dát reputaci sám sobě")
	}

	ctx := context.Background()
	date := time.Now().Format("20060102")
	limitKey := fmt.Sprintf("rep:limit:%s:%s", fromID, date)

	// 1. Check daily limit
	count, _ := redis_client.Client.Get(ctx, limitKey).Int()
	if count >= MaxDailyRep {
		return 0, fmt.Errorf("dnes jsi už vyčerpal svůj limit %d bodů", MaxDailyRep)
	}

	// 2. Pair cooldown check (24h)
	cooldownKey := fmt.Sprintf("rep:cooldown:%s:%s", fromID, toID)
	exists, _ := redis_client.Client.Exists(ctx, cooldownKey).Result()
	if exists > 0 {
		return 0, fmt.Errorf("tomuto uživateli jsi již reputaci v posledních 24 hodinách dal")
	}

	// 3. Atomically update all structures
	event := RepEvent{
		GiverID:   fromID,
		Reason:    reason,
		Timestamp: time.Now().Unix(),
		ChannelID: channelID,
	}
	eventJSON, _ := json.Marshal(event)

	pipe := redis_client.Client.Pipeline()
	
	// Increment total
	totalKey := fmt.Sprintf("rep:total:%s", toID)
	pipe.Incr(ctx, totalKey)
	
	// Track unique givers
	giversKey := fmt.Sprintf("rep:givers:%s", toID)
	pipe.SAdd(ctx, giversKey, fromID)
	
	// Log event
	eventsKey := fmt.Sprintf("rep:events:%s", toID)
	pipe.LPush(ctx, eventsKey, eventJSON)
	pipe.LTrim(ctx, eventsKey, 0, 99) // Keep last 100 events
	
	// Leaderboard update
	lbKey := fmt.Sprintf("rep:leaderboard:%s", guildID)
	pipe.ZIncrBy(ctx, lbKey, 1, toID)
	
	// Update daily limit
	pipe.Incr(ctx, limitKey)
	pipe.Expire(ctx, limitKey, 24*time.Hour)
	
	// Set pair cooldown
	pipe.Set(ctx, cooldownKey, "1", 24*time.Hour)

	_, err := pipe.Exec(ctx)
	if err != nil {
		return 0, err
	}

	newTotal, _ := redis_client.Client.Get(ctx, totalKey).Int()
	return newTotal, nil
}

func (r *ReputationService) GetStats(toID string) (total int, uniqueGivers int, lastReason string, trustScore string, rank string) {
	ctx := context.Background()
	
	total, _ = redis_client.Client.Get(ctx, fmt.Sprintf("rep:total:%s", toID)).Int()
	ug, _ := redis_client.Client.SCard(ctx, fmt.Sprintf("rep:givers:%s", toID)).Result()
	uniqueGivers = int(ug)
	
	lastEventRaw, _ := redis_client.Client.LIndex(ctx, fmt.Sprintf("rep:events:%s", toID), 0).Result()
	if lastEventRaw != "" {
		var ev RepEvent
		if err := json.Unmarshal([]byte(lastEventRaw), &ev); err == nil {
			lastReason = ev.Reason
		}
	}

	profileKey := fmt.Sprintf("rep:profile:%s", toID)
	profile, _ := redis_client.Client.HGetAll(ctx, profileKey).Result()
	if len(profile) > 0 {
		trustScore = profile["trust_score"]
		rank = profile["rank"]
	} else {
		trustScore = "0.0"
		rank = "New Member"
	}
	
	return
}

func (r *ReputationService) HandleCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	if len(options) == 0 {
		return
	}

	subcommand := options[0].Name
	switch subcommand {
	case "give":
		targetUser := options[0].Options[0].UserValue(s)
		reason := ""
		if len(options[0].Options) > 1 {
			reason = options[0].Options[1].StringValue()
		}

		newTotal, err := r.GiveRep(i.Member.User.ID, targetUser.ID, i.GuildID, i.ChannelID, reason)
		if err != nil {
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: fmt.Sprintf("❌ %s", err.Error()),
					Flags:   discordgo.MessageFlagsEphemeral,
				},
			})
			return
		}

		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: fmt.Sprintf("✅ Udělil jsi bod reputace uživateli %s! Nyní má celkem **%d** bodů.", targetUser.Mention(), newTotal),
			},
		})

	case "stats":
		targetUser := i.Member.User
		if len(options[0].Options) > 0 {
			targetUser = options[0].Options[0].UserValue(s)
		}
		
		total, givers, lastReason, trust, rank := r.GetStats(targetUser.ID)
		
		embed := &discordgo.MessageEmbed{
			Title: "👤 Reputační profil: " + targetUser.Username,
			Color: 0x3498db,
			Thumbnail: &discordgo.MessageEmbedThumbnail{
				URL: targetUser.AvatarURL("128"),
			},
			Fields: []*discordgo.MessageEmbedField{
				{Name: "Celková reputace", Value: fmt.Sprintf("**%d**", total), Inline: true},
				{Name: "Unikátní dárci", Value: fmt.Sprintf("**%d**", givers), Inline: true},
				{Name: "Trust Score", Value: fmt.Sprintf("**%s**", trust), Inline: true},
				{Name: "Rank", Value: fmt.Sprintf("**%s**", rank), Inline: true},
			},
		}
		
		if lastReason != "" {
			embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
				Name: "Poslední důvod", Value: fmt.Sprintf("*\"%s\"*", lastReason), Inline: false,
			})
		}

		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Embeds: []*discordgo.MessageEmbed{embed},
			},
		})

	case "top":
		ctx := context.Background()
		lbKey := fmt.Sprintf("rep:leaderboard:%s", i.GuildID)
		top, _ := redis_client.Client.ZRevRangeWithScores(ctx, lbKey, 0, 9).Result()
		
		if len(top) == 0 {
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: "Žebříček je zatím prázdný.",
					Flags:   discordgo.MessageFlagsEphemeral,
				},
			})
			return
		}

		desc := "**Top 10 nejužitečnějších členů:**\n\n"
		for idx, entry := range top {
			desc += fmt.Sprintf("**%d.** <@%s> — %v bodů\n", idx+1, entry.Member, entry.Score)
		}

		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Embeds: []*discordgo.MessageEmbed{
					{
						Title:       "🏆 Reputační Žebříček",
						Description: desc,
						Color:       0xf1c40f,
					},
				},
			},
		})
	}
}
