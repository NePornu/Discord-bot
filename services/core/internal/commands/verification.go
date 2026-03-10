package commands

import (
	"fmt"
	"log"
	"sync"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/keycloak"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

var (
	KcClient *keycloak.KeycloakClient
	once     sync.Once
)

func InitKeycloak(cfg *config.Config) {
	once.Do(func() {
		KcClient = keycloak.NewClient(cfg)
	})
}

func HandleSSOStatus(s *discordgo.Session, i *discordgo.InteractionCreate) {
	// Defer as Keycloak check might take a moment
	s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseDeferredChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{
			Flags: discordgo.MessageFlagsEphemeral,
		},
	})

	userID := i.Member.User.ID
	
	// 1. Check link in Redis
	kcUserID, err := redis_client.Client.Get(redis_client.Ctx, "sso:keycloak_link:"+userID).Result()
	if err != nil {
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: Pointer("❌ **Tvůj Discord účet není propojen s NePornu ID.**\nKlikni na tlačítko 'Propojit účet' výše a přihlas se."),
		})
		return
	}

	// 2. Fetch groups from Keycloak
	groups, err := KcClient.GetUserGroups(kcUserID)
	if err != nil {
		log.Printf("Error fetching groups for %s: %v", userID, err)
		s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
			Content: Pointer("❌ **Chyba při komunikaci s Keycloak.** Zkuste to prosím později."),
		})
		return
	}

	groupStr := ""
	for _, g := range groups {
		if gm, ok := g.(map[string]interface{}); ok {
			groupStr += fmt.Sprintf("- %s\n", gm["path"])
		}
	}

	if groupStr == "" {
		groupStr = "_Žádné speciální skupiny_"
	}

	resp := fmt.Sprintf("✅ **Ověření aktivní!**\n\n**Keycloak ID:** `%s`\n**Skupiny:**\n%s", kcUserID, groupStr)
	s.InteractionResponseEdit(i.Interaction, &discordgo.WebhookEdit{
		Content: &resp,
	})
}

func Pointer[T any](v T) *T {
	return &v
}
