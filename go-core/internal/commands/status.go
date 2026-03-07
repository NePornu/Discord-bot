package commands

import (
	"fmt"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
)

type StatusType string

const (
	Online           StatusType = "online"
	Maintenance      StatusType = "údržba"
	PlannedMaint     StatusType = "plánovaná_údržba"
	Outage           StatusType = "výpadek"
	PartialOutage    StatusType = "částečný_výpadek"
	DegradedPerf     StatusType = "snížený_výkon"
	Unstable         StatusType = "nestabilní"
	LimitedFunc      StatusType = "omezená_funkčnost"
	Investigating    StatusType = "vyšetřujeme"
	Monitoring       StatusType = "📡"
	Resolved         StatusType = "vyřešeno"
)

var StatusMap = map[StatusType]struct {
	Emoji string
	Color int
}{
	Online:        {"✅", 0x00FF00},
	Maintenance:   {"🛠️", 0xFFA500},
	PlannedMaint:  {"🗓️", 0xFFA500},
	Outage:        {"🔴", 0xFF0000},
	PartialOutage: {"🚧", 0xFF4500},
	DegradedPerf:  {"🐌", 0xFFD700},
	Unstable:      {"⚠️", 0xFFFF00},
	LimitedFunc:   {"⚙️", 0xFFA500},
	Investigating: {"🔎", 0x3498DB},
	Monitoring:    {"📡", 0x1ABC9C},
	Resolved:      {"✔️", 0x00CC00},
}

var CodeMap = map[string]StatusType{
	"1":  Online,
	"2":  Maintenance,
	"3":  PlannedMaint,
	"4":  Outage,
	"5":  PartialOutage,
	"6":  DegradedPerf,
	"7":  Unstable,
	"8":  LimitedFunc,
	"9":  Investigating,
	"10": Monitoring,
	"11": Resolved,
}

func HandleStatus(s *discordgo.Session, i *discordgo.InteractionCreate) {
	options := i.ApplicationCommandData().Options
	optionMap := make(map[string]*discordgo.ApplicationCommandInteractionDataOption)
	for _, opt := range options {
		optionMap[opt.Name] = opt
	}

	stateRaw := optionMap["stav"].StringValue()
	serviceName := optionMap["sluzba"].StringValue()
	details := ""
	if opt, ok := optionMap["podrobnosti"]; ok {
		details = opt.StringValue()
	}

	key := strings.ToLower(stateRaw)
	statusType, ok := CodeMap[key]
	if !ok {
		statusType = StatusType(key)
	}

	data, ok := StatusMap[statusType]
	if !ok {
		s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: "❌ Neplatný stav. Použijte kód (1-11) nebo název stavu.",
				Flags:   discordgo.MessageFlagsEphemeral,
			},
		})
		return
	}

	embed := &discordgo.MessageEmbed{
		Title:       fmt.Sprintf("Stav služby: %s", serviceName),
		Description: fmt.Sprintf("%s **%s**", data.Emoji, strings.Title(strings.ReplaceAll(string(statusType), "_", " "))),
		Color:       data.Color,
		Timestamp:   time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Odesláno: %s", i.Member.User.Username),
		},
	}

	if details != "" {
		embed.Fields = []*discordgo.MessageEmbedField{
			{
				Name:   "Podrobnosti",
				Value:  details,
				Inline: false,
			},
		}
	}

	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Embeds: []*discordgo.MessageEmbed{embed},
		},
	})
}
