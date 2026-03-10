package commands

import (
	"fmt"
	"math"
	"strconv"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type LevelsHandler struct {
	A       float64
	B       float64
	CBase   float64
}

func NewLevelsHandler() *LevelsHandler {
	return &LevelsHandler{
		A:     50,
		B:     200,
		CBase: 100,
	}
}

func (h *LevelsHandler) HandleRank(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{},
	})

	target := i.Member.User
	options := i.ApplicationCommandData().Options
	if len(options) > 0 {
		target = options[0].UserValue(s)
	}

	gid := i.GuildID
	uid := target.ID
	xpKey := fmt.Sprintf("levels:xp:%s", gid)

	score, _ := redis_client.Client.ZScore(redis_client.Ctx, xpKey, uid).Result()
	totalXP := int(score)
	level := h.calculateLevel(totalXP)

	rank, _ := redis_client.Client.ZRevRank(redis_client.Ctx, xpKey, uid).Result()
	rankDisplay := strconv.FormatInt(rank+1, 10)

	nextLevelXP := h.xpForLevel(level + 1)
	xpNeeded := nextLevelXP - totalXP

	embed := &discordgo.MessageEmbed{
		Title: fmt.Sprintf("Rank: %s", target.Username),
		Color: 0x00FF00,
		Thumbnail: &discordgo.MessageEmbedThumbnail{
			URL: target.AvatarURL(""),
		},
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Level", Value: strconv.Itoa(level), Inline: true},
			{Name: "Rank", Value: "#" + rankDisplay, Inline: true},
			{Name: "XP", Value: fmt.Sprintf("%d / %d", totalXP, nextLevelXP), Inline: false},
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Do dalšího levelu chybí %d XP", xpNeeded),
		},
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func (h *LevelsHandler) HandleLeaderboard(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{},
	})

	gid := i.GuildID
	xpKey := fmt.Sprintf("levels:xp:%s", gid)

	topUsers, err := redis_client.Client.ZRevRangeWithScores(redis_client.Ctx, xpKey, 0, 9).Result()
	if err != nil {
		content := "Žádná data pro leaderboard."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	var desc string
	for idx, member := range topUsers {
		xp := int(member.Score)
		level := h.calculateLevel(xp)
		desc += fmt.Sprintf("**%d.** <@%s> — **Lvl %d** (%d XP)\n", idx+1, member.Member.(string), level, xp)
	}

	embed := &discordgo.MessageEmbed{
		Title:       "🏆 XP Leaderboard",
		Description: desc,
		Color:       0xF1C40F,
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func (h *LevelsHandler) calculateLevel(xp int) int {
	if float64(xp) < h.CBase {
		return 0
	}
	c := h.CBase - float64(xp)
	d := (h.B * h.B) - (4 * h.A * c)
	if d < 0 {
		return 0
	}
	level := (-h.B + math.Sqrt(d)) / (2 * h.A)
	return int(level)
}

func (h *LevelsHandler) xpForLevel(level int) int {
	return int(h.A*float64(level*level) + h.B*float64(level) + h.CBase)
}
