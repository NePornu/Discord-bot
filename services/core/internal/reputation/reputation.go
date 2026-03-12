package reputation

import (
	"context"
	"fmt"
	"sort"
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

func (r *ReputationService) GiveRep(fromID, toID string) (int, error) {
	if fromID == toID {
		return 0, fmt.Errorf("nemůžeš dát reputaci sám sobě")
	}

	ctx := context.Background()
	date := time.Now().Format("2006-01-02")
	limitKey := fmt.Sprintf("rep:limit:%s:%s", fromID, date)

	// Check daily limit
	count, _ := redis_client.Client.Get(ctx, limitKey).Int()
	if count >= MaxDailyRep {
		return 0, fmt.Errorf("dnes jsi už vyčerpal svůj limit %d bodů", MaxDailyRep)
	}

	// Increment total reputation
	totalKey := fmt.Sprintf("rep:total:%s", toID)
	newTotal, err := redis_client.Client.Incr(ctx, totalKey).Result()
	if err != nil {
		return 0, err
	}

	// Increment daily limit counter
	redis_client.Client.Incr(ctx, limitKey)
	redis_client.Client.Expire(ctx, limitKey, 24*time.Hour)

	return int(newTotal), nil
}

func (r *ReputationService) GetStats(userID string) int {
	ctx := context.Background()
	totalKey := fmt.Sprintf("rep:total:%s", userID)
	val, _ := redis_client.Client.Get(ctx, totalKey).Int()
	return val
}

type LeaderboardEntry struct {
	UserID string
	Points int
}

func (r *ReputationService) GetLeaderboard() ([]LeaderboardEntry, error) {
	if redis_client.Client == nil {
		return nil, fmt.Errorf("Redis not available")
	}

	ctx := context.Background()
	var leaderboard []LeaderboardEntry

	// Use SCAN instead of KEYS to avoid blocking Redis
	var cursor uint64
	for {
		keys, nextCursor, err := redis_client.Client.Scan(ctx, cursor, "rep:total:*", 100).Result()
		if err != nil {
			return nil, err
		}

		for _, key := range keys {
			val, _ := redis_client.Client.Get(ctx, key).Int()
			userID := key[len("rep:total:"):]
			leaderboard = append(leaderboard, LeaderboardEntry{
				UserID: userID,
				Points: val,
			})
		}

		cursor = nextCursor
		if cursor == 0 {
			break
		}
	}

	// Sort by points descending
	sort.Slice(leaderboard, func(i, j int) bool {
		return leaderboard[i].Points > leaderboard[j].Points
	})

	// Return top 10
	if len(leaderboard) > 10 {
		leaderboard = leaderboard[:10]
	}

	return leaderboard, nil
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
		newTotal, err := r.GiveRep(i.Member.User.ID, targetUser.ID)
		if err != nil {
			content := fmt.Sprintf("❌ %s", err.Error())
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: content,
					Flags:   discordgo.MessageFlagsEphemeral,
				},
			})
			return
		}

		content := fmt.Sprintf("✅ Udělil jsi bod reputace uživateli %s! Nyní má celkem **%d** bodů.", targetUser.Mention(), newTotal)
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: content,
			},
		})

	case "stats":
		targetUser := i.Member.User
		if len(options[0].Options) > 0 {
			targetUser = options[0].Options[0].UserValue(s)
		}
		points := r.GetStats(targetUser.ID)
		content := fmt.Sprintf("👤 Uživatel %s má celkem **%d** bodů reputace.", targetUser.Mention(), points)
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: content,
			},
		})

	case "top":
		leaderboard, err := r.GetLeaderboard()
		if err != nil {
			content := "❌ Nepodařilo se načíst žebříček."
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: content,
				},
			})
			return
		}

		if len(leaderboard) == 0 {
			content := "Žebříček je zatím prázdný."
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: content,
				},
			})
			return
		}

		desc := "**Top 10 nejužitečnějších členů:**\n\n"
		for idx, entry := range leaderboard {
			desc += fmt.Sprintf("**%d.** <@%s> — %d bodů\n", idx+1, entry.UserID, entry.Points)
		}

		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Embeds: []*discordgo.MessageEmbed{
					{
						Title:       "🏆 Reputační Žebříček",
						Description: desc,
						Color:       0xf1c40f, // Gold
					},
				},
			},
		})
	}
}
