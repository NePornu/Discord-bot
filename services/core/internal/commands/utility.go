package commands

import (
	"fmt"
	"log/slog"

	"github.com/bwmarrin/discordgo"
)

func HandleEcho(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{},
	})

	content := i.ApplicationCommandData().Options[0].StringValue()

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
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
		slog.Error("Error bulk deleting", "error", err)
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

func HandleSay(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	var channelID string
	var content string

	for _, opt := range options {
		if opt.Name == "kanal" {
			channelID = opt.ChannelValue(s).ID
		} else if opt.Name == "zprava" {
			content = opt.StringValue()
		}
	}

	_, err := s.ChannelMessageSend(channelID, content)
	if err != nil {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "❌ Nepodařilo se odeslat zprávu: " + err.Error(),
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
		return
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: fmt.Sprintf("✅ Zpráva odeslána do <#%s>", channelID),
			Flags:   discordgo.MessageFlagsEphemeral,
		},
	})
}

func HandleEdit(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	var msgID string
	var newText string
	channelID := i.ChannelID

	for _, opt := range options {
		switch opt.Name {
		case "zprava_id":
			msgID = opt.StringValue()
		case "novy_text":
			newText = opt.StringValue()
		case "kanal":
			channelID = opt.ChannelValue(s).ID
		}
	}

	_, err := s.ChannelMessageEdit(channelID, msgID, newText)
	if err != nil {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "❌ Nepodařilo se upravit zprávu: " + err.Error(),
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
		return
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: "✅ Zpráva upravena.",
			Flags:   discordgo.MessageFlagsEphemeral,
		},
	})
}

func HandleDelete(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	var msgID string
	channelID := i.ChannelID

	for _, opt := range options {
		switch opt.Name {
		case "zprava_id":
			msgID = opt.StringValue()
		case "kanal":
			channelID = opt.ChannelValue(s).ID
		}
	}

	err := s.ChannelMessageDelete(channelID, msgID)
	if err != nil {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "❌ Nepodařilo se smazat zprávu: " + err.Error(),
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
		return
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Content: "✅ Zpráva smazána.",
			Flags:   discordgo.MessageFlagsEphemeral,
		},
	})
}
