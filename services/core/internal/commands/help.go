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

	options := i.ApplicationCommandData().Options
	var specificCmd string
	if len(options) > 0 && options[0].Name == "prikaz" {
		specificCmd = options[0].StringValue()
	}

	if specificCmd != "" {
		handleSpecificHelp(s, i, cmdList, specificCmd)
		return
	}

	// Categorize commands
	categories := map[string][]string{
		"📢 Obecné":            {"ping", "help", "echo", "gdpr", "report"},
		"🛡️ Moderace":          {"purge", "status", "verify", "automod", "notify", "patterns", "nsfwsync"},
		"📈 Statistiky & Levely": {"stats", "rank", "rank-leaderboard", "activity", "activity-leaderboard"},
		"🎮 Komunita":          {"challenge", "rep"},
	}

	embed := &discordgo.MessageEmbed{
		Title:       "👋 Vítejte v NePornu Botovi!",
		Description: "Tady je seznam všech dostupných příkazů rozdělených do kategorií.\nPro detaily o konkrétním příkazu použij `/help prikaz:název`.",
		Color:       0x5865F2, // Discord Blurple
		Thumbnail: &discordgo.MessageEmbedThumbnail{
			URL: "https://i.imgur.com/8N9B9vS.png", // Replace with bot logo if available
		},
		Footer: &discordgo.MessageEmbedFooter{
			Text: "NePornu Bot • Pomocník pro vaši komunitu",
		},
	}

	for catName, cmdNames := range categories {
		var catCmds []string
		for _, name := range cmdNames {
			// Find command in list to make sure it exists and get description
			for _, c := range cmdList {
				if c.Name == name {
					catCmds = append(catCmds, fmt.Sprintf("`/%s`", c.Name))
					break
				}
			}
		}
		if len(catCmds) > 0 {
			embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
				Name:   catName,
				Value:  strings.Join(catCmds, ", "),
				Inline: false,
			})
		}
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}

func handleSpecificHelp(s *discordgo.Session, i *discordgo.InteractionCreate, cmdList []*discordgo.ApplicationCommand, name string) {
	var targetCmd *discordgo.ApplicationCommand
	for _, c := range cmdList {
		if c.Name == name {
			targetCmd = c
			break
		}
	}

	if targetCmd == nil {
		content := fmt.Sprintf("❌ Příkaz `/%s` nebyl nalezen.", name)
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{Content: &content})
		return
	}

	embed := &discordgo.MessageEmbed{
		Title:       fmt.Sprintf("📖 Dokumentace: `/%s`", targetCmd.Name),
		Description: targetCmd.Description,
		Color:       0x00FF7F, // Spring Green
	}

	if len(targetCmd.Options) > 0 {
		var subcommands []string
		var parameters []string

		for _, opt := range targetCmd.Options {
			if opt.Type == discordgo.ApplicationCommandOptionSubCommand {
				subcommands = append(subcommands, fmt.Sprintf("• `/%s %s` - %s", targetCmd.Name, opt.Name, opt.Description))
			} else if opt.Type == discordgo.ApplicationCommandOptionSubCommandGroup {
				// Handle subcommand groups if any (nested subcommands)
				for _, subOpt := range opt.Options {
					subcommands = append(subcommands, fmt.Sprintf("• `/%s %s %s` - %s", targetCmd.Name, opt.Name, subOpt.Name, subOpt.Description))
				}
			} else {
				req := ""
				if opt.Required {
					req = " (povinné)"
				}
				parameters = append(parameters, fmt.Sprintf("• `%s` - %s%s", opt.Name, opt.Description, req))
			}
		}

		if len(subcommands) > 0 {
			embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
				Name:  "Subpříkazy",
				Value: strings.Join(subcommands, "\n"),
			})
		}

		if len(parameters) > 0 {
			embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
				Name:  "Parametry",
				Value: strings.Join(parameters, "\n"),
			})
		}
	}

	// Add permission info if applicable
	if targetCmd.DefaultMemberPermissions != nil {
		perm := *targetCmd.DefaultMemberPermissions
		if perm&int64(discordgo.PermissionAdministrator) != 0 {
			embed.Footer = &discordgo.MessageEmbedFooter{Text: "🛡️ Vyžaduje Administrátorská oprávnění"}
		} else if perm&int64(discordgo.PermissionKickMembers) != 0 {
			embed.Footer = &discordgo.MessageEmbedFooter{Text: "⚔️ Vyžaduje Moderátorská oprávnění"}
		}
	}

	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Embeds: &[]*discordgo.MessageEmbed{embed},
	})
}
