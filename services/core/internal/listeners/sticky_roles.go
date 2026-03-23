package listeners

import (
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
)

type StickyRolesListener struct {
	Config *config.Config
}

func NewStickyRolesListener(cfg *config.Config) *StickyRolesListener {
	return &StickyRolesListener{Config: cfg}
}

func (l *StickyRolesListener) OnMemberRemove(s *discordgo.Session, m *discordgo.GuildMemberRemove) {
	if m.User.Bot || redis_client.Client == nil {
		return
	}

	// m.Member might be nil if not in state, but discordgo usually populates it if possible.
	member := m.Member
	if member == nil {
		// Try to fallback to state if possible, though it's likely already gone
		member, _ = s.State.Member(m.GuildID, m.User.ID)
	}

	if member == nil {
		slog.Warn("Could not find member roles on leave (member nil)", "userID", m.User.ID)
		return
	}

	// Filter out @everyone (which has the same ID as the guild) and the waiting role
	var usefulRoles []string
	for _, roleID := range member.Roles {
		if roleID != m.GuildID && roleID != l.Config.WaitingRoleID {
			usefulRoles = append(usefulRoles, roleID)
		}
	}

	if len(usefulRoles) == 0 {
		return
	}

	key := fmt.Sprintf("sticky_roles:%s:%s", m.GuildID, m.User.ID)
	rolesStr := strings.Join(usefulRoles, ",")

	err := redis_client.Client.Set(redis_client.Ctx, key, rolesStr, 30*24*time.Hour).Err()
	if err != nil {
		slog.Error("Failed to save sticky roles", "userID", m.User.ID, "error", err)
	} else {
		slog.Info("Saved sticky roles for user", "userID", m.User.ID, "roles", rolesStr)
	}
}

func (l *StickyRolesListener) OnMemberJoin(s *discordgo.Session, m *discordgo.GuildMemberAdd) {
	if m.User.Bot || redis_client.Client == nil {
		return
	}

	key := fmt.Sprintf("sticky_roles:%s:%s", m.GuildID, m.User.ID)
	rolesStr, err := redis_client.Client.Get(redis_client.Ctx, key).Result()
	if err != nil {
		return // No sticky roles found
	}

	if rolesStr == "" {
		return
	}

	roles := strings.Split(rolesStr, ",")
	count := 0
	
	// Add a small delay to ensure Discord processed the join properly
	time.AfterFunc(2*time.Second, func() {
		for _, roleID := range roles {
			err := s.GuildMemberRoleAdd(m.GuildID, m.User.ID, roleID)
			if err != nil {
				slog.Error("Failed to restore sticky role", "userID", m.User.ID, "roleID", roleID, "error", err)
			} else {
				count++
			}
		}

		if count > 0 {
			slog.Info("Restored sticky roles for user", "userID", m.User.ID, "count", count)
		}
	})
}
