package commands

import (
	"fmt"
	"sort"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

func HandleActivityStats(s *discordgo.Session, i *discordgo.InteractionCreate) {
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

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Embeds: []*discordgo.MessageEmbed{embed},
		},
	})
}

func HandleActivityLeaderboard(s *discordgo.Session, i *discordgo.InteractionCreate) {
	gid := i.GuildID
	pattern := fmt.Sprintf("events:msg:%s:*", gid)
	keys, _ := redis_client.Client.Keys(redis_client.Ctx, pattern).Result()

	type userScore struct {
		ID    string
		Count int64
	}
	var scores []userScore

	// pattern is "events:msg:Gid:Uid"
	prefix := fmt.Sprintf("events:msg:%s:", gid)

	for _, k := range keys {
		uid := k[len(prefix):]
		count, _ := redis_client.Client.ZCard(redis_client.Ctx, k).Result()
		scores = append(scores, userScore{ID: uid, Count: count})
	}

	sort.Slice(scores, func(i, j int) bool {
		return scores[i].Count > scores[j].Count
	})

	var desc string
	limit := 10
	if len(scores) < limit { limit = len(scores) }
	
	for idx, sc := range scores[:limit] {
		desc += fmt.Sprintf("**%d.** <@%s> — `%d` zpráv\n", idx+1, sc.ID, sc.Count)
	}

	embed := &discordgo.MessageEmbed{
		Title:       "🏆 Activity Leaderboard (Zprávy)",
		Description: desc,
		Color:       0xE67E22,
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Embeds: []*discordgo.MessageEmbed{embed},
		},
	})
}
