package redis_client

import (
	"context"
	"log"
	"time"

	"github.com/redis/go-redis/v9"
)

var (
	Client *redis.Client
	Ctx    = context.Background()
)

func Init(redisURL string) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Fatalf("Error parsing Redis URL: %v", err)
	}

	Client = redis.NewClient(opts)
	
	// Add retry logic
	for i := 0; i < 5; i++ {
		_, err = Client.Ping(Ctx).Result()
		if err == nil {
			log.Println("Connected to Redis successfully")
			return
		}
		log.Printf("Attempt %d: Error connecting to Redis: %v. Retrying in 2s...", i+1, err)
		time.Sleep(2 * time.Second)
	}
	
	log.Fatalf("Error connecting to Redis after 5 attempts: %v", err)
}
