package stats

import (
	"fmt"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

func TrackUser(uid string, gid string) {
	today := time.Now().Format("2006-01-02")
	key := fmt.Sprintf("stats:hll:unique:%s:%s", gid, today)
	redis_client.Client.PFAdd(redis_client.Ctx, key, uid)
	redis_client.Client.Expire(redis_client.Ctx, key, 7*24*time.Hour)
}

func GetUniqueCount(gid string, day string) (int64, error) {
	key := fmt.Sprintf("stats:hll:unique:%s:%s", gid, day)
	return redis_client.Client.PFCount(redis_client.Ctx, key).Result()
}
