package tasks

import (
	"log"
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

			for _, guild := range s.State.Guilds {
				// discordgo's Guild structure has MemberCount
				totalMembers := guild.MemberCount
				
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
				pipe.SetEx(redis_client.Ctx, "presence:total:"+guild.ID, strconv.Itoa(int(totalMembers)), 60*time.Second)
				
				// Minimal sync of other guild metadata
				pipe.SAdd(redis_client.Ctx, "bot:guilds", guild.ID)
				
				_, err := pipe.Exec(redis_client.Ctx)
				if err != nil {
					log.Printf("[ERROR] MemberStats sync failed for guild %s: %v", guild.ID, err)
				}
			}
		}
	}()
}
