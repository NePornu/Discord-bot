package listeners

import (
	"fmt"
	"math/rand"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/leveling"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type LevelsListener struct {
	cfg   leveling.LevelConfig
	MinXP int
	MaxXP int
}

func NewLevelsListener() *LevelsListener {
	return &LevelsListener{
		cfg:   leveling.DefaultConfig(),
		MinXP: 15,
		MaxXP: 25,
	}
}

func (l *LevelsListener) OnMessage(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID == "" {
		return
	}

	uid := m.Author.ID
	gid := m.GuildID
	cooldownKey := fmt.Sprintf("levels:cooldown:%s:%s", gid, uid)

	exists, _ := redis_client.Client.Exists(redis_client.Ctx, cooldownKey).Result()
	if exists > 0 {
		return
	}

	xpGain := rand.Intn(l.MaxXP-l.MinXP+1) + l.MinXP
	xpKey := fmt.Sprintf("levels:xp:%s", gid)

	newXP, err := redis_client.Client.ZIncrBy(redis_client.Ctx, xpKey, float64(xpGain), uid).Result()
	if err != nil {
		return
	}

	redis_client.Client.SetEx(redis_client.Ctx, cooldownKey, "1", 60*time.Second)

	currentLevel := leveling.CalculateLevel(l.cfg, int(newXP))
	prevXP := int(newXP) - xpGain
	prevLevel := leveling.CalculateLevel(l.cfg, prevXP)

	if currentLevel > prevLevel {
		fmt.Printf("User %s leveled up to %d\n", uid, currentLevel)
	}
}
