package listeners

import (
	"fmt"
	"math"
	"math/rand"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type LevelsListener struct {
	A       float64
	B       float64
	CBase   float64
	MinXP   int
	MaxXP   int
}

func NewLevelsListener() *LevelsListener {
	return &LevelsListener{
		A:     50,
		B:     200,
		CBase: 100,
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

	currentLevel := l.calculateLevel(int(newXP))
	prevXP := int(newXP) - xpGain
	prevLevel := l.calculateLevel(prevXP)

	if currentLevel > prevLevel {
		fmt.Printf("User %s leveled up to %d\n", uid, currentLevel)
	}
}

func (l *LevelsListener) calculateLevel(xp int) int {
	if float64(xp) < l.CBase {
		return 0
	}
	c := l.CBase - float64(xp)
	d := (l.B * l.B) - (4 * l.A * c)
	if d < 0 {
		return 0
	}
	level := (-l.B + math.Sqrt(d)) / (2 * l.A)
	return int(level)
}
