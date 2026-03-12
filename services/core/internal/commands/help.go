package commands

import (
	"fmt"
	"strings"

	"github.com/bwmarrin/discordgo"
)

func HandleHelp(s *discordgo.Session, i *discordgo.InteractionCreate, cmdList []*discordgo.ApplicationCommand) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	var sb strings.Builder
	sb.WriteString("👋 **Vítejte v NePornu Botovi!**\n\n")
	sb.WriteString("Tady je seznam dostupných příkazů:\n\n")

	for _, cmd := range cmdList {
		sb.WriteString(fmt.Sprintf("• `/%s` - %s\n", cmd.Name, cmd.Description))
		if len(cmd.Options) > 0 {
			for _, opt := range cmd.Options {
				if opt.Type == discordgo.ApplicationCommandOptionSubCommand {
					sb.WriteString(fmt.Sprintf("  └ `/%s %s` - %s\n", cmd.Name, opt.Name, opt.Description))
				}
			}
		}
	}

	sb.WriteString("\n*Některé příkazy jsou dostupné pouze pro moderátory nebo administrátory.*")

	content := sb.String()
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}
