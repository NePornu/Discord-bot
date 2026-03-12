package commands

import (
	"fmt"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/stats"
)

func HandleServerStats(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	gid := i.GuildID
	today := time.Now().Format("2006-01-02")
	yesterday := time.Now().AddDate(0, 0, -1).Format("2006-01-02")

	uniqueToday, _ := stats.GetUniqueCount(gid, today)
	uniqueYesterday, _ := stats.GetUniqueCount(gid, yesterday)

	embed := &discordgo.MessageEmbed{
		Title: "📊 Statistiky Serveru",
		Color: 0x3498DB,
		Fields: []*discordgo.MessageEmbedField{
			{
				Name:   "👥 Unikátní uživatelé (Dnes)",
				Value:  fmt.Sprintf("**%d**", uniqueToday),
				Inline: true,
			},
			{
				Name:   "👥 Unikátní uživatelé (Včera)",
				Value:  fmt.Sprintf("**%d**", uniqueYesterday),
				Inline: true,
			},
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: "Data jsou založena na HLL (HyperLogLog) odhadech.",
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}
