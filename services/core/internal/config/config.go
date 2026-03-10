package config

import (
	"log"
	"os"

	"github.com/joho/godotenv"
)

type Config struct {
	BotToken            string
	RedisURL            string
	KCAdminPassword     string
	KCInternalURL       string
	AlertChannelID      string
	DashboardToken      string
	GuildID             string
	VerificationChannel string
	VerifLogChannel     string
	WelcomeChannel      string
	VerifiedRole        string
	VerificationCode    string
	ConsoleChannelID    string
	WaitLogChannelID    string
	WaitingRoleID       string
}

func LoadConfig() *Config {
	// Try to load .env from several locations
	envPaths := []string{".env", "../.env", "/app/.env"}
	for _, path := range envPaths {
		if err := godotenv.Load(path); err == nil {
			log.Printf("Loaded config from %s", path)
			break
		}
	}

	cleanEnv := func(key string) string {
		val := os.Getenv(key)
		// Strip quotes if any
		if len(val) >= 2 && ((val[0] == '"' && val[len(val)-1] == '"') || (val[0] == '\'' && val[len(val)-1] == '\'')) {
			return val[1 : len(val)-1]
		}
		return val
	}

	return &Config{
		BotToken:            cleanEnv("BOT_TOKEN"),
		RedisURL:            cleanEnv("REDIS_URL"),
		KCAdminPassword:     cleanEnv("KC_ADMIN_PASSWORD"),
		KCInternalURL:       cleanEnv("KC_INTERNAL_URL"),
		AlertChannelID:      cleanEnv("ALERT_CHANNEL_ID"),
		DashboardToken:      cleanEnv("DASHBOARD_TOKEN"),
		GuildID:             cleanEnv("GUILD_ID"),
		VerificationChannel: cleanEnv("VERIFICATION_CHANNEL_ID"),
		VerifLogChannel:     cleanEnv("VERIFICATION_LOG_CHANNEL_ID"),
		WelcomeChannel:      cleanEnv("WELCOME_CHANNEL_ID"),
		VerifiedRole:        cleanEnv("VERIFIED_ROLE_ID"),
		VerificationCode:    cleanEnv("VERIFICATION_CODE"),
		ConsoleChannelID:    cleanEnv("CONSOLE_CHANNEL_ID"),
		WaitLogChannelID:    cleanEnv("WAIT_LOG_CHANNEL_ID"),
		WaitingRoleID:       cleanEnv("WAITING_ROLE_ID"),
	}
}
