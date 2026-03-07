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

	return &Config{
		BotToken:        os.Getenv("BOT_TOKEN"),
		RedisURL:        os.Getenv("REDIS_URL"),
		KCAdminPassword: os.Getenv("KC_ADMIN_PASSWORD"),
		KCInternalURL:   os.Getenv("KC_INTERNAL_URL"),
		AlertChannelID:  os.Getenv("ALERT_CHANNEL_ID"),
		DashboardToken:      os.Getenv("DASHBOARD_TOKEN"),
		GuildID:             os.Getenv("GUILD_ID"),
		VerificationChannel: os.Getenv("VERIFICATION_CHANNEL_ID"),
		VerifLogChannel:     os.Getenv("VERIFICATION_LOG_CHANNEL_ID"),
		WelcomeChannel:      os.Getenv("WELCOME_CHANNEL_ID"),
		VerifiedRole:        os.Getenv("VERIFIED_ROLE_ID"),
		VerificationCode:    os.Getenv("VERIFICATION_CODE"),
	}
}
