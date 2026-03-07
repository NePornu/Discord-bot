package listeners

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
	"github.com/nepornucz/discord-bot-core/internal/stats"
	"github.com/redis/go-redis/v9"
)

type ActivityListener struct{}

func NewActivityListener() *ActivityListener {
	return &ActivityListener{}
}

func (l *ActivityListener) OnMessage(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID == "" {
		return
	}

	gid := m.GuildID
	uid := m.Author.ID
	ts := float64(m.Timestamp.Unix())
	
	key := fmt.Sprintf("events:msg:%s:%s", gid, uid)
	
	eventData, _ := json.Marshal(map[string]interface{}{
		"mid":   m.ID,
		"len":   len(m.Content),
		"reply": m.ReferencedMessage != nil,
	})

	redis_client.Client.ZAdd(redis_client.Ctx, key, redis.Z{
		Score:  ts,
		Member: string(eventData),
	})

	stats.TrackUser(uid, gid)

	l.UpdateUserInfo(m.Author, m.Member)
}

func (l *ActivityListener) UpdateUserInfo(user *discordgo.User, member *discordgo.Member) {
	key := fmt.Sprintf("user:info:%s", user.ID)
	
	roles := ""
	if member != nil {
		for i, r := range member.Roles {
			if i > 0 {
				roles += ","
			}
			roles += r
		}
	}

	redis_client.Client.HSet(redis_client.Ctx, key, map[string]interface{}{
		"name":   user.Username,
		"avatar": user.AvatarURL(""),
		"roles":  roles,
	})
	redis_client.Client.Expire(redis_client.Ctx, key, 7*24*time.Hour)
}
