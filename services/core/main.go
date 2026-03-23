package main

import (
	"fmt"
	"log/slog"
	"net/http"
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
	fullMsg := "```[" + ts + "] " + msg + "```"
	_, err := s.ChannelMessageSend(channelID, fullMsg)
	if err != nil {
		slog.Error("Failed to send console log", "error", err)
	}
}

func main() {
	// Initialize structured logging
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	defer func() {
		if r := recover(); r != nil {
			slog.Error("CRITICAL PANIC RECOVERED", "error", r)
		}
	}()

	slog.Info("Initializing Go Core (REWRITE)")
	cfg := config.LoadConfig()

	if cfg.BotToken == "" {
		slog.Error("BOT_TOKEN is missing in environment!")
		os.Exit(1)
	}

	slog.Info("Config Loaded", "redis", cfg.RedisURL != "", "guild", cfg.GuildID)

	// Initialize Redis with retry
	if cfg.RedisURL != "" {
		slog.Info("Connecting to Redis", "url", cfg.RedisURL)
		redis_client.Init(cfg.RedisURL)
		slog.Info("Redis Connected")

		if !tasks.AcquireInstanceLock() {
			slog.Error("Instance lock is already taken by another process!")
			os.Exit(1)
		}
		tasks.StartLockRefresh()
		slog.Info("Instance lock acquired")
	} else {
		slog.Warn("Redis URL is empty. Skipping Redis-dependent services.")
	}

	// Initialize Services
	slog.Info("Initializing Subservices")
	if redis_client.Client == nil && cfg.RedisURL != "" {
		slog.Error("Redis client is nil but URL was provided. Cannot proceed.")
		os.Exit(1)
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
	stickyRolesListener := listeners.NewStickyRolesListener(cfg)
	
	// Calendar service strictly needs Redis
	var calendarService *calendar.CalendarService
	if redis_client.Client != nil {
		calendarService = calendar.NewCalendarService(cfg, redis_client.Client)
		slog.Info("Calendar Service Initialized")
	} else {
		slog.Warn("Calendar Service Skipped (No Redis)")
	}
	
	slog.Info("Basic Subservices Initialized")

	dg, err := discordgo.New("Bot " + cfg.BotToken)
	if err != nil {
		slog.Error("Error creating Discord session", "error", err)
		os.Exit(1)
	}

	// Enable intents
	dg.Identify.Intents = discordgo.IntentsAll
	dg.StateEnabled = true

	// Register slash commands
	cmdList := []*discordgo.ApplicationCommand{
		{
			Name:        "ping",
			Description: "Replies with Pong!",
		},
		{
			Name:        "help",
			Description: "Zobrazí nápovědu k botovi",
			Options: []*discordgo.ApplicationCommandOption{
				{
					Type:        discordgo.ApplicationCommandOptionString,
					Name:        "prikaz",
					Description: "Konkrétní příkaz, o kterém chceš vědět víc",
					Required:    false,
				},
			},
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
			Name:        "stats",
			Description: "Statistiky serveru a bota",
			Options: []*discordgo.ApplicationCommandOption{
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "server",
					Description: "Zobrazí aktuální statistiky serveru",
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
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "progress",
					Description: "Zobrazí statistiky ověření členů (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "broadcast",
					Description: "Aktivuje chytré pošťouchnutí pro neověřené (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "admin",
					Description: "🛡️ Správa a přehled ověřování (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "toggle",
					Description: "Zapne/vypne systém pošťuchování (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "onboarding",
					Description: "Odešle menu pro ověření věku (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "bulk-migrate",
					Description: "Převede uživatele v čekárně na nový systém (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "bulk-reverify",
					Description: "Spustí hromadné ověřování všech členů (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "reset-age",
					Description: "Resetuje kompletní proces ověření uživatele (Admin)",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionUser,
							Name:        "uzivatel",
							Description: "Uživatel k resetování",
							Required:    true,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "reset",
					Description: "Resetuje kompletní proces ověření uživatele (Admin)",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionUser,
							Name:        "uzivatel",
							Description: "Uživatel k resetování",
							Required:    true,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "bulk-all",
					Description: "Pošle nové ověření VŠEM členům na serveru (Admin)",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionBoolean,
							Name:        "dry-run",
							Description: "Pouze spočítá uživatele, nic neposílá",
							Required:    false,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "list-waiting",
					Description: "Zobrazí seznam uživatelů v čekárně (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "list-db",
					Description: "Zobrazí seznam prověřených uživatelů z databáze (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "audit-ages",
					Description: "Prohledá historii zpráv a najde zmínky o věku (Admin)",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "redis-audit",
					Description: "Zobrazí audit dat v Redis (Admin)",
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
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "link-toggle",
					Description: "Zapnout/vypnout schvalování odkazů",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionBoolean,
							Name:        "zapnuto",
							Description: "Status schvalování",
							Required:    true,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "link-channel",
					Description: "Nastavit kanál pro schvalování odkazů",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionChannel,
							Name:        "kanal",
							Description: "Kanál pro schvalování",
							Required:    true,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "exempt-add",
					Description: "Přidat roli, kanál nebo kategorii do výjimek",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionRole,
							Name:        "role",
							Description: "Role k ignorování",
							Required:    false,
						},
						{
							Type:        discordgo.ApplicationCommandOptionChannel,
							Name:        "kanal",
							Description: "Kanál k ignorování",
							Required:    false,
						},
						{
							Type:        discordgo.ApplicationCommandOptionChannel,
							Name:        "kategorie",
							Description: "Kategorie k ignorování",
							Required:    false,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "exempt-remove",
					Description: "Odstranit z výjimek",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionString,
							Name:        "role",
							Description: "ID role k odstranění",
							Required:    false,
						},
						{
							Type:        discordgo.ApplicationCommandOptionString,
							Name:        "kanal",
							Description: "ID kanálu k odstranění",
							Required:    false,
						},
						{
							Type:        discordgo.ApplicationCommandOptionString,
							Name:        "kategorie",
							Description: "ID kategorie k odstranění",
							Required:    false,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "exempt-list",
					Description: "Zobrazit seznam všech výjimek",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "status",
					Description: "Zobrazit aktuální nastavení AutoModu",
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
		{
			Name:        "patterns",
			Description: "Detekce vzorců chování (Python)",
			Options: []*discordgo.ApplicationCommandOption{
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "check",
					Description: "Ručně zkontrolovat vzorce u konkrétního uživatele",
					Options: []*discordgo.ApplicationCommandOption{
						{
							Type:        discordgo.ApplicationCommandOptionUser,
							Name:        "user",
							Description: "Uživatel ke kontrole",
							Required:    true,
						},
					},
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "status",
					Description: "Zobrazí stav pattern detection enginu",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "list",
					Description: "Seznam uživatelů s detekovanými vzorci",
				},
				{
					Type:        discordgo.ApplicationCommandOptionSubCommand,
					Name:        "info",
					Description: "Informace o dostupných vzorcích",
				},
			},
		},
		{
			Name:        "nsfwsync",
			Description: "Manuální sken profilovek na serveru (Python)",
			Options: []*discordgo.ApplicationCommandOption{
				{
					Type:        discordgo.ApplicationCommandOptionInteger,
					Name:        "limit",
					Description: "Maximální počet uživatelů k otestování",
					Required:    false,
				},
				{
					Type:        discordgo.ApplicationCommandOptionUser,
					Name:        "user",
					Description: "Konkrétní uživatel k otestování",
					Required:    false,
				},
			},
		},
	}

	// Set permissions
	adminPerm := int64(discordgo.PermissionAdministrator)
	modPerm := int64(discordgo.PermissionKickMembers)
	for _, cmd := range cmdList {
		switch cmd.Name {
		case "purge", "echo", "status", "notify", "stats":
			cmd.DefaultMemberPermissions = &adminPerm
		case "verify", "automod":
			cmd.DefaultMemberPermissions = &modPerm
		}
	}

	// Register handlers
	dg.AddHandler(func(s *discordgo.Session, r *discordgo.Ready) {
		slog.Info("Bot is online", "user", s.State.User.Username+"#"+s.State.User.Discriminator)
		
		guildID := cfg.GuildID
		if guildID == "" {
			slog.Info("Registering commands GLOBALLY")
		} else {
			slog.Info("Registering commands for GUILD", "guildID", guildID)
		}

		_, err := s.ApplicationCommandBulkOverwrite(s.State.User.ID, guildID, cmdList)
		if err != nil {
			slog.Error("Cannot bulk register commands", "error", err)
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
		case "help":
			commands.HandleHelp(s, i, cmdList)
		case "stats":
			commands.HandleServerStats(s, i)
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
	dg.AddHandler(logHandler.OnMessageCreate)
	dg.AddHandler(logHandler.OnGuildMemberAdd)
	dg.AddHandler(logHandler.OnGuildMemberRemove)
	dg.AddHandler(logHandler.OnGuildMemberUpdate)
	dg.AddHandler(logHandler.OnVoiceStateUpdate)
	dg.AddHandler(logHandler.OnGuildBanAdd)
	dg.AddHandler(logHandler.OnGuildBanRemove)
	dg.AddHandler(logHandler.OnChannelCreate)
	dg.AddHandler(logHandler.OnChannelDelete)
	dg.AddHandler(logHandler.OnChannelUpdate)
	dg.AddHandler(logHandler.OnMessageReactionAdd)
	dg.AddHandler(logHandler.OnMessageReactionRemove)
	dg.AddHandler(logHandler.OnMessageReactionRemoveAll)
	dg.AddHandler(logHandler.OnInteractionCreate)
	dg.AddHandler(logHandler.OnGuildRoleCreate)
	dg.AddHandler(logHandler.OnGuildRoleUpdate)
	dg.AddHandler(logHandler.OnGuildRoleDelete)
	dg.AddHandler(logHandler.OnGuildUpdate)
	dg.AddHandler(logHandler.OnThreadCreate)
	dg.AddHandler(logHandler.OnThreadDelete)
	dg.AddHandler(logHandler.OnInviteCreate)
	dg.AddHandler(logHandler.OnInviteDelete)
	dg.AddHandler(logHandler.OnWebhooksUpdate)
	dg.AddHandler(logHandler.OnGuildScheduledEventCreate)
	dg.AddHandler(logHandler.OnGuildScheduledEventUpdate)
	dg.AddHandler(logHandler.OnGuildScheduledEventDelete)
	dg.AddHandler(logHandler.OnAutoModerationActionExecution)
	dg.AddHandler(logHandler.OnAutoModerationRuleCreate)
	dg.AddHandler(logHandler.OnAutoModerationRuleUpdate)
	dg.AddHandler(logHandler.OnAutoModerationRuleDelete)
	dg.AddHandler(logHandler.OnMessageDeleteBulk)
	dg.AddHandler(logHandler.OnGuildEmojisUpdate)
	dg.AddHandler(verifyService.OnMemberRemove)

	// Custom Listeners
	dg.AddHandler(levelsListener.OnMessage)
	dg.AddHandler(activityListener.OnMessage)
	dg.AddHandler(stickyRolesListener.OnMemberRemove)
	dg.AddHandler(stickyRolesListener.OnMemberJoin)

	dg.AddHandler(verifyService.OnMemberJoin)
	dg.AddHandler(verifyService.OnMessageCreate)
	dg.AddHandler(automodService.OnMessage)
	dg.AddHandler(automodService.OnMessageUpdate)
	dg.AddHandler(challengeService.OnMessage)
	dg.AddHandler(challengeService.OnReactionAdd)

	// Interaction Handler (Buttons / Selects / Modals)
	dg.AddHandler(func(s *discordgo.Session, i *discordgo.InteractionCreate) {
		slog.Info("Interaction received", "type", i.Type, "userID", verifyService.GetUserIDFromInteraction(i))
		defer func() {
			if r := recover(); r != nil {
				slog.Error("RECOVERED PANIC in interaction handler", "error", r, "type", i.Type)
				// Try to respond to Discord if it was a component or modal interaction
				if i.Type == discordgo.InteractionMessageComponent || i.Type == discordgo.InteractionModalSubmit {
					s.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
						Type: discordgo.InteractionResponseChannelMessageWithSource,
						Data: &discordgo.InteractionResponseData{
							Content: "⚠️ V aplikaci došlo k chybě. Prosím kontaktujte administrátora.",
							Flags:   discordgo.MessageFlagsEphemeral,
						},
					})
				}
			}
		}()

		switch i.Type {
		case discordgo.InteractionMessageComponent:
			verifyService.HandleButtonClick(s, i)
			automodService.HandleInteraction(s, i)
			if calendarService != nil {
				calendarService.HandleInteraction(s, i)
			}
		case discordgo.InteractionModalSubmit:
			verifyService.HandleModalSubmit(s, i)
		}
	})

	slog.Info("Opening Discord connection")
	err = dg.Open()
	if err != nil {
		slog.Error("Error opening connection", "error", err)
		os.Exit(1)
	}
	slog.Info("Discord connection opened successfully")

	// Start background tasks
	tasks.StartHeartbeat()
	tasks.StartMemberStats(dg)

	// Start Health Check HTTP server
	go func() {
		http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("OK"))
		})
		slog.Info("Health check server starting", "port", 8080)
		if err := http.ListenAndServe(":8080", nil); err != nil {
			slog.Error("Health check server failed", "error", err)
		}
	}()

	slog.Info("Bot is now running. Press CTRL-C to exit.")
	sc := make(chan os.Signal, 1)
	signal.Notify(sc, syscall.SIGINT, syscall.SIGTERM, os.Interrupt)
	<-sc

	// Graceful shutdown: release instance lock
	slog.Info("Shutting down...")
	if redis_client.Client != nil {
		lockKey := "bot:lock:primary"
		redis_client.Client.Del(redis_client.Ctx, lockKey)
		slog.Info("Instance lock released")
	}

	dg.Close()
}
