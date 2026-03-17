package stats

import (
	"fmt"
	"time"

	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

// RecordJoin increments the join counter for the current month in Redis.
func RecordJoin(guildID string) {
	if redis_client.Client == nil {
		return
	}
	currMonth := time.Now().Format("2006-01")
	key := fmt.Sprintf("stats:joins:%s", guildID)
	redis_client.Client.HIncrBy(redis_client.Ctx, key, currMonth, 1)
}

// RecordLeave increments the leave counter for the current month in Redis.
func RecordLeave(guildID string) {
	if redis_client.Client == nil {
		return
	}
	currMonth := time.Now().Format("2006-01")
	key := fmt.Sprintf("stats:leaves:%s", guildID)
	redis_client.Client.HIncrBy(redis_client.Ctx, key, currMonth, 1)
}
