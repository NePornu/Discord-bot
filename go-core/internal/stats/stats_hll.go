package stats

import (
	"fmt"
	"time"

	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

func TrackUser(uid string, gid string) {
	if redis_client.Client == nil {
		return
	}
	today := time.Now().Format("2006-01-02")
	key := fmt.Sprintf("stats:hll:unique:%s:%s", gid, today)
	redis_client.Client.PFAdd(redis_client.Ctx, key, uid)
	redis_client.Client.Expire(redis_client.Ctx, key, 7*24*time.Hour)
}

func GetUniqueCount(gid string, day string) (int64, error) {
	if redis_client.Client == nil {
		return 0, fmt.Errorf("redis client not initialized")
	}
	key := fmt.Sprintf("stats:hll:unique:%s:%s", gid, day)
	return redis_client.Client.PFCount(redis_client.Ctx, key).Result()
}
