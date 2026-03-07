package notifications

import (
	"fmt"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
)

type NotifyService struct {
	Config *config.Config
}

func NewNotifyService(cfg *config.Config) *NotifyService {
	return &NotifyService{Config: cfg}
}

func (n *NotifyService) HandleNotifyCommand(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	message := options[0].StringValue()
	target := "ALL"
	if len(options) > 1 {
		target = options[1].StringValue()
	}

	// Permission check
	if (i.Member.Permissions & discordgo.PermissionAdministrator) == 0 {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: "❌ Pouze administrátoři mohou posílat oznámení.", Flags: 64},
		})
		return
	}

	// 1. Initial confirmation view
	embed := &discordgo.MessageEmbed{
		Title:       "⚠️ Potvrzení hromadného rozesílání",
		Description: fmt.Sprintf("**Zpráva:** %s\n**Cíl:** %s\n\nRozesílání trvá dlouho (3-5 minut na uživatele) kvůli ochraně proti banu.", message, target),
		Color:       0xffa500,
		Timestamp:   time.Now().Format(time.RFC3339),
	}

	btnConfirm := discordgo.Button{
		Label:    "Potvrdit a odeslat",
		Style:    discordgo.SuccessButton,
		CustomID: "notify_confirm",
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Embeds: []*discordgo.MessageEmbed{embed},
			Components: []discordgo.MessageComponent{
				discordgo.ActionsRow{
					Components: []discordgo.MessageComponent{btnConfirm},
				},
			},
		},
	})
}
