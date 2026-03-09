package commands

import (
	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
)

func HandleReport(s *discordgo.Session, i *discordgo.InteractionCreate, cfg *config.Config) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	options := i.ApplicationCommandData().Options
	optionMap := make(map[string]*discordgo.ApplicationCommandInteractionDataOption)
	for _, opt := range options {
		optionMap[opt.Name] = opt
	}

	target := optionMap["uzivatel"].UserValue(s)
	reason := optionMap["duvod"].StringValue()

	content := "✅ Nahlášení bylo odesláno moderátorům."
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})

	embed := &discordgo.MessageEmbed{
		Title: "🚩 Nové nahlášení",
		Color: 0xFF5555,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Nahlášený:", Value: target.Mention(), Inline: true},
			{Name: "Nahlásil:", Value: i.Member.User.Mention(), Inline: true},
			{Name: "Důvod:", Value: reason, Inline: false},
		},
	}

	s.ChannelMessageSendEmbed(cfg.AlertChannelID, embed)
}

func HandleGDPR(s *discordgo.Session, i *discordgo.InteractionCreate) {
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	content := "📜 **Vaše data v NePornu Botu**\n\nPodle GDPR máte právo na výpis dat. Náš bot o vás ukládá:\n" +
		"- Discord ID a uživatelské jméno\n" +
		"- Datum připojení na server\n" +
		"- Informace o propojení s NePornu ID (pokud jste se ověřili)\n\n" +
		"Pro úplný výpis nebo smazání kontaktujte administrátory."

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &content,
	})
}
