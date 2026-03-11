package tasks

import (
	"log"
	"os"
	"strconv"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

func StartHeartbeat() {
	ticker := time.NewTicker(60 * time.Second)
	go func() {
		for range ticker.C {
			if redis_client.Client == nil {
				continue
			}
			err := redis_client.Client.Set(redis_client.Ctx, "bot:heartbeat", strconv.FormatInt(time.Now().Unix(), 10), 0).Err()
			if err != nil {
				log.Printf("[ERROR] Heartbeat failed: %v", err)
			}
		}
	}()
}

func StartMemberStats(s *discordgo.Session) {
	ticker := time.NewTicker(10 * time.Second)
	go func() {
		for range ticker.C {
			if s.State == nil {
				continue
			}

			totalMembersAllGuilds := 0

			for _, guild := range s.State.Guilds {
				totalMembersAllGuilds += int(guild.MemberCount)
				
				// For online count, it's more complex as we need Presences intent
				onlineCount := 0
				for _, p := range guild.Presences {
					if p.Status != discordgo.StatusOffline {
						onlineCount++
					}
				}

				if redis_client.Client == nil {
					continue
				}

				pipe := redis_client.Client.Pipeline()
				pipe.SetEx(redis_client.Ctx, "presence:online:"+guild.ID, strconv.Itoa(onlineCount), 60*time.Second)
				pipe.SetEx(redis_client.Ctx, "presence:total:"+guild.ID, strconv.Itoa(int(guild.MemberCount)), 60*time.Second)
				
				// Minimal sync of other guild metadata
				pipe.SAdd(redis_client.Ctx, "bot:guilds", guild.ID)
				
				_, err := pipe.Exec(redis_client.Ctx)
				if err != nil {
					log.Printf("[ERROR] MemberStats sync failed for guild %s: %v", guild.ID, err)
				}
			}

			// Update global presence
			statusMsg := "Na serveru je: " + strconv.Itoa(totalMembersAllGuilds)
			err := s.UpdateStatusComplex(discordgo.UpdateStatusData{
				Activities: []*discordgo.Activity{
					{
						Name: statusMsg,
						Type: discordgo.ActivityTypeWatching,
					},
				},
				Status: "online",
			})
			if err != nil {
				log.Printf("[ERROR] Failed to update presence: %v", err)
			}
		}
	}()
}

func AcquireInstanceLock() bool {
	if redis_client.Client == nil {
		return true // If Redis is disabled, we can't lock, but we shouldn't block start unless strictly required
	}

	lockKey := "bot:lock:primary"
	myID := strconv.Itoa(os.Getpid())

	// Try to set the lock with a 60-second TTL
	success, err := redis_client.Client.SetNX(redis_client.Ctx, lockKey, myID, 60*time.Second).Result()
	if err != nil {
		log.Printf("[ERROR] Failed to check instance lock: %v", err)
		return false
	}

	if !success {
		// Check if we already own it (e.g. from a quick restart)
		val, _ := redis_client.Client.Get(redis_client.Ctx, lockKey).Result()
		if val == myID {
			log.Printf("[INFO] Re-acquired lock held by same PID (%s)", myID)
			redis_client.Client.Expire(redis_client.Ctx, lockKey, 60*time.Second)
			return true
		}
	}

	return success
}

func StartLockRefresh() {
	ticker := time.NewTicker(10 * time.Second)
	go func() {
		lockKey := "bot:lock:primary"
		myID := strconv.Itoa(os.Getpid())

		for range ticker.C {
			if redis_client.Client == nil {
				continue
			}

			val, err := redis_client.Client.Get(redis_client.Ctx, lockKey).Result()
			if err != nil {
				log.Printf("[ERROR] Lock refresh failed (get): %v", err)
				continue
			}

			if val == myID {
				// We own the lock, refresh it for 60 more seconds
				redis_client.Client.Expire(redis_client.Ctx, lockKey, 60*time.Second)
			} else {
				log.Printf("[CRITICAL] Instance lock stolen by PID %s! Shutting down to prevent duplicate handling.", val)
				os.Exit(1)
			}
		}
	}()
}
