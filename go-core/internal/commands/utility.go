package commands

import (
	"fmt"
	"log"

	"github.com/bwmarrin/discordgo"
)

func HandleEcho(s *discordgo.Session, i *discordgo.InteractionCreate) {
	content := i.ApplicationCommandData().Options[0].StringValue()

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: content,
		},
	})
}

func HandlePurge(s *discordgo.Session, i *discordgo.InteractionCreate) {
	// Check permissions manually if not using DefaultMemberPermissions
	amount := int(i.ApplicationCommandData().Options[0].IntValue())
	if amount > 100 {
		amount = 100
	}

	// Defer as deleting messages might take time
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	messages, err := s.ChannelMessages(i.ChannelID, amount, "", "", "")
	if err != nil {
		content := "❌ Nepodařilo se načíst zprávy."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	var msgIDs []string
	for _, m := range messages {
		msgIDs = append(msgIDs, m.ID)
	}

	err = s.ChannelMessagesBulkDelete(i.ChannelID, msgIDs)
	if err != nil {
		log.Printf("Error bulk deleting: %v", err)
		content := "❌ Nepodařilo se smazat zprávy (zprávy starší 14 dnů nelze hromadně mazat)."
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: &content,
		})
		return
	}

	content := fmt.Sprintf("✅ Smazáno %d zpráv.", len(msgIDs))
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}
