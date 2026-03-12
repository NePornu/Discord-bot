package commands

import (
	"fmt"
	"sort"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

func HandleActivityStats(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{},
	})

	target := i.Member.User
	options := i.ApplicationCommandData().Options
	for _, opt := range options {
		if opt.Name == "uzivatel" {
			target = opt.UserValue(s)
		}
	}

	gid := i.GuildID
	uid := target.ID

	msgKey := fmt.Sprintf("events:msg:%s:%s", gid, uid)
	msgCount, _ := redis_client.Client.ZCard(redis_client.Ctx, msgKey).Result()

	embed := &discordgo.MessageEmbed{
		Title: fmt.Sprintf("📊 Aktivita: %s", target.Username),
		Color: 0x3498db,
		Thumbnail: &discordgo.MessageEmbedThumbnail{
			URL: target.AvatarURL(""),
		},
		Fields: []*discordgo.MessageEmbedField{
			{Name: "📩 Počet zpráv", Value: fmt.Sprintf("%d", msgCount), Inline: true},
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: "Data vygenerována z Go Core",
		},
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func HandleActivityLeaderboard(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{},
	})

	gid := i.GuildID
	prefix := fmt.Sprintf("events:msg:%s:", gid)

	type userScore struct {
		ID    string
		Count int64
	}
	var scores []userScore

	// Use SCAN instead of KEYS to avoid blocking Redis
	var cursor uint64
	for {
		keys, nextCursor, err := redis_client.Client.Scan(redis_client.Ctx, cursor, prefix+"*", 100).Result()
		if err != nil {
			break
		}
		for _, k := range keys {
			uid := k[len(prefix):]
			count, _ := redis_client.Client.ZCard(redis_client.Ctx, k).Result()
			scores = append(scores, userScore{ID: uid, Count: count})
		}
		cursor = nextCursor
		if cursor == 0 {
			break
		}
	}

	sort.Slice(scores, func(i, j int) bool {
		return scores[i].Count > scores[j].Count
	})

	var desc string
	limit := 10
	if len(scores) < limit {
		limit = len(scores)
	}

	for idx, sc := range scores[:limit] {
		desc += fmt.Sprintf("**%d.** <@%s> — `%d` zpráv\n", idx+1, sc.ID, sc.Count)
	}

	embed := &discordgo.MessageEmbed{
		Title:       "🏆 Activity Leaderboard (Zprávy)",
		Description: desc,
		Color:       0xE67E22,
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}
