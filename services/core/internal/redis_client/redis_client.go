package redis_client

import (
	"context"
	"log/slog"
	"os"
	"time"

	"github.com/redis/go-redis/v9"
)

var (
	Client *redis.Client
	Ctx    = context.Background()
)

// Timeout returns a context with a 2-second timeout for Redis operations.
// Use this for operations that shouldn't hang indefinitely.
func Timeout() (context.Context, context.CancelFunc) {
	return context.WithTimeout(Ctx, 2*time.Second)
}

func Init(redisURL string) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		slog.Error("Error parsing Redis URL", "error", err)
		os.Exit(1)
	}

	// Set stricter timeouts to fit within Discord's 3s interaction limit
	opts.ReadTimeout = 2 * time.Second
	opts.WriteTimeout = 2 * time.Second
	opts.PoolTimeout = 3 * time.Second

	Client = redis.NewClient(opts)
	
	// Add retry logic
	for i := 0; i < 5; i++ {
		_, err = Client.Ping(Ctx).Result()
		if err == nil {
			slog.Info("Connected to Redis successfully")
			return
		}
		slog.Warn("Error connecting to Redis", "attempt", i+1, "error", err)
		time.Sleep(2 * time.Second)
	}
	
	slog.Error("Error connecting to Redis after 5 attempts", "error", err)
	os.Exit(1)
}
