package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
	"github.com/nepornucz/discord-bot-core/internal/commands"
	"github.com/nepornucz/discord-bot-core/internal/tasks"
	"github.com/nepornucz/discord-bot-core/internal/logging"
	"github.com/nepornucz/discord-bot-core/internal/listeners"
	"github.com/nepornucz/discord-bot-core/internal/verification"
	"github.com/nepornucz/discord-bot-core/internal/automod"
	"github.com/nepornucz/discord-bot-core/internal/notifications"
	"github.com/nepornucz/discord-bot-core/internal/challenge"
	"github.com/nepornucz/discord-bot-core/internal/calendar"
	"github.com/nepornucz/discord-bot-core/internal/reputation"
)

func sendConsoleLog(s *discordgo.Session, channelID string, msg string) {
	if channelID == "" {
		return
	}
	ts := time.Now().Format("2006-01-02 15:04:05")
	fullMsg := fmt.Sprintf("```[%s] %s```", ts, msg)
	_, err := s.ChannelMessageSend(channelID, fullMsg)
	if err != nil {
		log.Printf("Failed to send console log: %v", err)
	}
}

func main() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Printf("CRITICAL PANIC RECOVERED: %v\n", r)
			log.Printf("CRITICAL PANIC: %v", r)
		}
	}()

	fmt.Println("=== INITIALIZING GO CORE (REWRITE) ===")
	cfg := config.LoadConfig()

	if cfg.BotToken == "" {
		log.Fatal("BOT_TOKEN is missing in environment!")
	}

	fmt.Printf("Config Loaded. Redis: %s | Guild: %s\n", cfg.RedisURL, cfg.GuildID)

	// Initialize Redis with retry
	if cfg.RedisURL != "" {
		fmt.Printf("Connecting to Redis: %s...\n", cfg.RedisURL)
		redis_client.Init(cfg.RedisURL)
		fmt.Println("✅ Redis Connected.")

		if !tasks.AcquireInstanceLock() {
			log.Fatal("❌ [ERROR] Instance lock is already taken by another process!")
		}
		tasks.StartLockRefresh()
		fmt.Println("✅ Instance lock acquired.")
	} else {
		fmt.Println("⚠️ Redis URL is empty. Skipping Redis-dependent services.")
	}

	// Initialize Services
	fmt.Println("Initializing Subservices...")
	if redis_client.Client == nil && cfg.RedisURL != "" {
		log.Fatal("Redis client is nil but URL was provided. Cannot proceed.")
	}

	logHandler := logging.NewLogger(cfg)
	levelsListener := listeners.NewLevelsListener()
	activityListener := listeners.NewActivityListener()
	verifyService := verification.NewVerificationService(cfg)
	automodService := automod.NewAutoModService(cfg)
	notifyService := notifications.NewNotifyService(cfg)
	challengeService := challenge.NewChallengeService(cfg)
	repService := reputation.NewReputationService(cfg)
	levelsHandler := commands.NewLevelsHandler()
	
	// Calendar service strictly needs Redis
	var calendarService *calendar.CalendarService
	if redis_client.Client != nil {
		calendarService = calendar.NewCalendarService(cfg, redis_client.Client)
		fmt.Println("✅ Calendar Service Initialized.")
	} else {
		fmt.Println("⚠️ Calendar Service Skipped (No Redis).")
	}
	
	fmt.Println("✅ Basic Subservices Initialized.")

	dg, err := discordgo.New("Bot " + cfg.BotToken)
	if err != nil {
		fmt.Printf("FATAL: Discord Creation Error: %v\n", err)
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
			{
				Name:        "verify",
				Description: "Příkazy pro ověření uživatelů",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "bypass",
						Description: "Manuálně schválí uživatele",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionUser,
								Name:        "uzivatel",
								Description: "Uživatel k schválení",
								Required:    true,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "set_bypass",
						Description: "Nastaví tajné bypass heslo",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "heslo",
								Description: "Nové heslo",
								Required:    true,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "ping",
						Description: "Pošle ti testovací DM s OTP",
					},
				},
			},
			{
				Name:        "automod",
				Description: "Správa automatické moderace",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "filter-add",
						Description: "Přidat regex filtr",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "pattern",
								Description: "Regex vzor",
								Required:    true,
							},
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "action",
								Description: "Akce (approve/auto_reject)",
								Choices: []*discordgo.ApplicationCommandOptionChoice{
									{Name: "Schválení", Value: "approve"},
									{Name: "Auto-Reject", Value: "auto_reject"},
								},
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "filter-list",
						Description: "Seznam filtrů",
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "filter-remove",
						Description: "Odstranit filtr",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionInteger,
								Name:        "index",
								Description: "Číslo filtru k odstranění",
								Required:    true,
							},
						},
					},
				},
			},
			{
				Name:        "notify",
				Description: "Poslat hromadné DM oznámení (Admin only)",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "zprava",
						Description: "Text oznámení",
						Required:    true,
					},
					{
						Type:        discordgo.ApplicationCommandOptionString,
						Name:        "cil",
						Description: "Cíl (ALL nebo název role)",
						Required:    false,
					},
				},
			},
			{
				Name:        "challenge",
				Description: "Správa výzev",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "setup",
						Description: "Vytvořit nebo upravit výzvu",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "id",
								Description: "Unikátní ID výzvy (např. nelednacek)",
								Required:    true,
							},
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "pattern",
								Description: "Vzor zprávy (např. Quest —)",
								Required:    false,
							},
							{
								Type:        discordgo.ApplicationCommandOptionChannel,
								Name:        "channel",
								Description: "Kanál pro výzvu",
								Required:    false,
							},
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "start",
								Description: "Datum zahájení (YYYYMMDD)",
								Required:    false,
							},
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "end",
								Description: "Datum ukončení (YYYYMMDD)",
								Required:    false,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "milestone",
						Description: "Přidat milník k výzvě",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "id",
								Description: "ID výzvy",
								Required:    true,
							},
							{
								Type:        discordgo.ApplicationCommandOptionInteger,
								Name:        "days",
								Description: "Počet dní",
								Required:    true,
							},
							{
								Type:        discordgo.ApplicationCommandOptionRole,
								Name:        "role",
								Description: "Role k udělení",
								Required:    true,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "info",
						Description: "Informace o výzvě",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionString,
								Name:        "id",
								Description: "ID výzvy (volitelné)",
								Required:    false,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "stats",
						Description: "Tvůj pokrok ve výzvě",
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "backfill",
						Description: "Doplnit historii výzvy (Admin)",
					},
				},
			},
			{
				Name:        "rep",
				Description: "Systém reputace a hodnocení členů",
				Options: []*discordgo.ApplicationCommandOption{
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "give",
						Description: "Udělí bod reputace uživateli",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionUser,
								Name:        "uzivatel",
								Description: "Uživatel, kterému chceš dát bod",
								Required:    true,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "stats",
						Description: "Zobrazí počet bodů reputace",
						Options: []*discordgo.ApplicationCommandOption{
							{
								Type:        discordgo.ApplicationCommandOptionUser,
								Name:        "uzivatel",
								Description: "Uživatel (volitelné)",
								Required:    false,
							},
						},
					},
					{
						Type:        discordgo.ApplicationCommandOptionSubCommand,
						Name:        "top",
						Description: "Zobrazí žebříček nejvíce nápomocných členů",
					},
				},
			},
		}

		adminPerm := int64(discordgo.PermissionAdministrator)
		modPerm := int64(discordgo.PermissionKickMembers)

		for _, cmd := range cmdList {
			switch cmd.Name {
			case "purge", "echo", "status", "notify":
				cmd.DefaultMemberPermissions = &adminPerm
			case "verify", "automod":
				cmd.DefaultMemberPermissions = &modPerm
			}
		}

		_, err := s.ApplicationCommandBulkOverwrite(s.State.User.ID, "", cmdList)
		if err != nil {
			log.Printf("Cannot bulk register commands: %v", err)
		}

		if cfg.ConsoleChannelID != "" {
			host, _ := os.Hostname()
			uptimeMs := time.Now().Format("2006-01-02 15:04:05")
			
			// Build dynamic list of commands
			cmdNames := make([]string, len(cmdList))
			for i, cmd := range cmdList {
				cmdNames[i] = cmd.Name
			}
			cmdListStr := strings.Join(cmdNames, ", ")

			sendConsoleLog(s, cfg.ConsoleChannelID, "[=== GO CORE SPUŠTĚN ===]")
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("Čas: %s", uptimeMs))
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("Platforma: %s %s | Go: %s", runtime.GOOS, runtime.GOARCH, runtime.Version()))
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("discordgo: %s", discordgo.VERSION))
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("PID: %d | Host: %s", os.Getpid(), host))
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("Registrované příkazy (%d):\n- %s", len(cmdList), cmdListStr))
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("Služby: Redis=%v, Keycloak=%v", cfg.RedisURL != "", cfg.KCInternalURL != ""))
			sendConsoleLog(s, cfg.ConsoleChannelID, "Načtené moduly: internal/verification, internal/automod, internal/notifications, internal/challenge, internal/calendar, internal/stats, internal/logging, internal/commands")
			sendConsoleLog(s, cfg.ConsoleChannelID, fmt.Sprintf("=== KONFIGURACE KANÁLŮ ===\n- Admin Console: %s\n- Verifikace (Mod): %s\n- Logy Verifikace: %s\n- Welcome: %s\n- Alerts: %s", 
				cfg.ConsoleChannelID, cfg.VerificationChannel, cfg.VerifLogChannel, cfg.WelcomeChannel, cfg.AlertChannelID))
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
			levelsHandler.HandleRank(s, i)
		case "rank-leaderboard":
			levelsHandler.HandleLeaderboard(s, i)
		case "activity":
			commands.HandleActivityStats(s, i)
		case "activity-leaderboard":
			commands.HandleActivityLeaderboard(s, i)
		case "status":
			commands.HandleStatus(s, i)
		case "verify":
			verifyService.HandleVerifyCommand(s, i)
		case "automod":
			automodService.HandleAutoModCommand(s, i)
		case "notify":
			notifyService.HandleNotifyCommand(s, i)
		case "challenge":
			challengeService.HandleChallengeCommand(s, i)
		case "rep":
			repService.HandleCommand(s, i)
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

	dg.AddHandler(verifyService.OnMemberJoin)
	dg.AddHandler(verifyService.OnMessageCreate)
	dg.AddHandler(automodService.OnMessage)
	dg.AddHandler(automodService.OnMessageUpdate)
	dg.AddHandler(challengeService.OnMessage)
	dg.AddHandler(challengeService.OnReactionAdd)

	// Interaction Handler (Buttons / Selects)
	dg.AddHandler(func(s *discordgo.Session, i *discordgo.InteractionCreate) {
		if i.Type == discordgo.InteractionMessageComponent {
			verifyService.HandleButtonClick(s, i)
			automodService.HandleInteraction(s, i)
			if calendarService != nil {
				calendarService.HandleInteraction(s, i)
			}
		}
	})

	fmt.Println("Opening Discord connection...")
	err = dg.Open()
	if err != nil {
		fmt.Printf("Fatalf: Error opening connection: %v\n", err)
		log.Fatalf("Error opening connection: %v", err)
	}
	fmt.Println("Success: Discord connection opened.")

	// Start background tasks
	tasks.StartHeartbeat()
	tasks.StartMemberStats(dg)

	log.Println("Bot is now running. Press CTRL-C to exit.")
	sc := make(chan os.Signal, 1)
	signal.Notify(sc, syscall.SIGINT, syscall.SIGTERM, os.Interrupt)
	<-sc

	// Graceful shutdown: release instance lock
	log.Println("Shutting down...")
	if redis_client.Client != nil {
		lockKey := "bot:lock:primary"
		redis_client.Client.Del(redis_client.Ctx, lockKey)
		log.Println("Instance lock released.")
	}

	dg.Close()
}
