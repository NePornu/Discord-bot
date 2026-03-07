package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
	"github.com/nepornucz/discord-bot-core/internal/commands"
	"github.com/nepornucz/discord-bot-core/internal/tasks"
	"github.com/nepornucz/discord-bot-core/internal/logging"
	"github.com/nepornucz/discord-bot-core/internal/listeners"
	"github.com/nepornucz/discord-bot-core/internal/verification"
)

func main() {
	cfg := config.LoadConfig()

	if cfg.BotToken == "" {
		log.Fatal("BOT_TOKEN must be set")
	}

	// Initialize Redis
	if cfg.RedisURL != "" {
		redis_client.Init(cfg.RedisURL)
	}

	// Initialize Keycloak
	commands.InitKeycloak(cfg)

	// Initialize Logger
	logHandler := logging.NewLogger(cfg)

	// Initialize Listeners
	levelsListener := listeners.NewLevelsListener()
	activityListener := listeners.NewActivityListener()

	dg, err := discordgo.New("Bot " + cfg.BotToken)
	if err != nil {
		log.Fatalf("Error creating Discord session: %v", err)
	}

	// Enable intents
	dg.Identify.Intents = discordgo.IntentsAll
	dg.StateEnabled = true

	// Register handlers
	dg.AddHandler(func(s *discordgo.Session, r *discordgo.Ready) {
		log.Printf("Bot is online: %s#%s", s.State.User.Username, s.State.User.Discriminator)
		
		// Register slash commands
		cmdList := []*discordgo.ApplicationCommand{
			{
				Name:        "ping",
				Description: "Replies with Pong!",
			},
			{
				Name:        "echo",
				Description: "Repeats your message",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "zprava",
						Description: "Zpráva k opakování",
						Required:    true,
					},
				},
			},
			{
				Name:        "purge",
				Description: "Smaže určitý počet zpráv",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionInteger,
						Name:        "pocet",
						Description: "Počet zpráv ke smazání (max 100)",
						Required:    true,
					},
				},
			},
			{
				Name:        "report",
				Description: "Nahlásit uživatele moderátorům",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionUser,
						Name:        "uzivatel",
						Description: "Uživatel k nahlášení",
						Required:    true,
					},
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "duvod",
						Description: "Důvod nahlášení",
						Required:    true,
					},
				},
			},
			{
				Name:        "gdpr",
				Description: "Zobrazit informace o vašich datech",
			},
			{
				Name:        "rank",
				Description: "Zobrazí tvůj aktuální level a XP",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionUser,
						Name:        "uzivatel",
						Description: "Uživatel k zobrazení",
						Required:    false,
					},
				},
			},
			{
				Name:        "activity",
				Description: "Zobrazí tvou aktivitu na serveru",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionUser,
						Name:        "uzivatel",
						Description: "Uživatel k zobrazení",
						Required:    false,
					},
				},
			},
			{
				Name:        "rank-leaderboard",
				Description: "TOP 10 uživatelů podle XP",
			},
			{
				Name:        "activity-leaderboard",
				Description: "TOP 10 nejaktivnějších (podle zpráv)",
			},
			{
				Name:        "sso_status",
				Description: "Check your Keycloak/SSO verification status",
			},
			{
				Name:        "status",
				Description: "Odešle embed s aktuálním stavem služby",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "stav",
						Description: "Kód (1-11) nebo název stavu",
						Required:    true,
					},
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "sluzba",
						Description: "Název služby",
						Required:    true,
					},
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "podrobnosti",
						Description: "Dodatečné informace",
						Required:    false,
					},
				},
			},
		}

		for _, cmd := range cmdList {
			_, err := s.ApplicationCommandCreate(s.State.User.ID, "", cmd)
			if err != nil {
				log.Printf("Cannot create command %v: %v", cmd.Name, err)
			}
		}
	})

	dg.AddHandler(func(s *discordgo.Session, i *discordgo.InteractionCreate) {
		if i.Type != discordgo.InteractionApplicationCommand {
			return
		}

		switch i.ApplicationCommandData().Name {
		case "ping":
			s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
				Type: discordgo.InteractionResponseChannelMessageWithSource,
				Data: &discordgo.InteractionResponseData{
					Content: "Pong from Go! 🏓",
				},
			})
		case "echo":
			commands.HandleEcho(s, i)
		case "purge":
			commands.HandlePurge(s, i)
		case "report":
			commands.HandleReport(s, i, cfg)
		case "gdpr":
			commands.HandleGDPR(s, i)
		case "rank":
			levelsHandler := commands.NewLevelsHandler()
			levelsHandler.HandleRank(s, i)
		case "rank-leaderboard":
			levelsHandler := commands.NewLevelsHandler()
			levelsHandler.HandleLeaderboard(s, i)
		case "activity":
			commands.HandleActivityStats(s, i)
		case "activity-leaderboard":
			commands.HandleActivityLeaderboard(s, i)
		case "sso_status":
			commands.HandleSSOStatus(s, i)
		case "status":
			commands.HandleStatus(s, i)
		}
	})

	// Logging handlers
	dg.AddHandler(logHandler.OnMessageDelete)
	dg.AddHandler(logHandler.OnMessageUpdate)
	dg.AddHandler(logHandler.OnGuildMemberAdd)
	dg.AddHandler(logHandler.OnGuildMemberRemove)

	// Custom Listeners
	dg.AddHandler(levelsListener.OnMessage)
	dg.AddHandler(activityListener.OnMessage)

	// Initialize Verification Service
	verifyService := verification.NewVerificationService(cfg)

	// Interaction Handler (Buttons / Selects)
	dg.AddHandler(func(s *discordgo.Session, i *discordgo.InteractionCreate) {
		if i.Type == discordgo.InteractionMessageComponent {
			verifyService.HandleButtonClick(s, i)
		}
	})

	err = dg.Open()
	if err != nil {
		log.Fatalf("Error opening connection: %v", err)
	}

	// Start background tasks
	tasks.StartHeartbeat()
	tasks.StartMemberStats(dg)

	log.Println("Bot is now running. Press CTRL-C to exit.")
	sc := make(chan os.Signal, 1)
	signal.Notify(sc, syscall.SIGINT, syscall.SIGTERM, os.Interrupt)
	<-sc

	dg.Close()
}
