package logging

import (
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
	"github.com/nepornucz/discord-bot-core/internal/redis_client"
	"github.com/nepornucz/discord-bot-core/internal/stats"
)

type Logger struct {
	Config *config.Config
	sl     *slog.Logger
}

func NewLogger(cfg *config.Config) *Logger {
	return &Logger{
		Config: cfg,
		sl:     slog.Default(),
	}
}

func (l *Logger) OnMessageDelete(s *discordgo.Session, m *discordgo.MessageDelete) {
	oldMsg, err := s.State.Message(m.ChannelID, m.ID)
	
	embed := &discordgo.MessageEmbed{
		Title:     "🗑️ Zpráva smazána",
		Color:     0xFF0000,
		Timestamp: time.Now().Format(time.RFC3339),
	}

	if err == nil && oldMsg != nil && oldMsg.Author != nil {
		content := oldMsg.Content
		if content == "" {
			if len(oldMsg.Attachments) > 0 {
				content = fmt.Sprintf("_[Příloha: %s]_", oldMsg.Attachments[0].Filename)
			} else {
				content = "_[Žádný textový obsah]_"
			}
		}
		embed.Description = fmt.Sprintf("**Autor:** %s\n**Kanál:** <#%s>\n\n**Obsah:**\n%s", oldMsg.Author.Mention(), m.ChannelID, content)
		embed.Footer = &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("User ID: %s | ID: %s", oldMsg.Author.ID, m.ID),
		}
	} else if redis_client.Client != nil {
		// Try Redis cache
		key := fmt.Sprintf("msg:cache:%s", m.ID)
		cached, _ := redis_client.Client.HGetAll(redis_client.Ctx, key).Result()
		if len(cached) > 0 {
			content := cached["content"]
			if content == "" {
				content = "_[Žádný textový obsah]_"
			}
			embed.Description = fmt.Sprintf("**Autor:** %s\n**Kanál:** <#%s>\n\n**Obsah (z mezipaměti):**\n%s", cached["author"], m.ChannelID, content)
			embed.Footer = &discordgo.MessageEmbedFooter{
				Text: fmt.Sprintf("User ID: %s | ID: %s", cached["uid"], m.ID),
			}
			// Clean up
			redis_client.Client.Del(redis_client.Ctx, key)
		} else {
			embed.Description = fmt.Sprintf("**Kanál:** <#%s>\n\n*Obsah zprávy není v paměti bota (zpráva byla příliš stará nebo byl bot restartován).*", m.ChannelID)
			embed.Footer = &discordgo.MessageEmbedFooter{
				Text: fmt.Sprintf("ID: %s", m.ID),
			}
		}
	} else {
		embed.Description = fmt.Sprintf("**Kanál:** <#%s>\n\n*Obsah zprávy není v paměti bota.*", m.ChannelID)
		embed.Footer = &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("ID: %s", m.ID),
		}
	}

	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnMessageCreate(s *discordgo.Session, m *discordgo.MessageCreate) {
	if m.Author.Bot || m.GuildID == "" {
		return
	}

	if redis_client.Client == nil {
		return
	}

	key := fmt.Sprintf("msg:cache:%s", m.ID)
	data := map[string]interface{}{
		"content": m.Content,
		"author":  m.Author.Mention(),
		"uid":     m.Author.ID,
	}
	
	redis_client.Client.HSet(redis_client.Ctx, key, data)
	redis_client.Client.Expire(redis_client.Ctx, key, 24*time.Hour)
}

func (l *Logger) OnMessageUpdate(s *discordgo.Session, m *discordgo.MessageUpdate) {
	if m.BeforeUpdate == nil || m.Author == nil || m.Author.Bot {
		return
	}

	if m.BeforeUpdate.Content == m.Content {
		return
	}

	embed := &discordgo.MessageEmbed{
		Title:       "📝 Zpráva upravena",
		Description: fmt.Sprintf("**Autor:** %s\n**Kanál:** <#%s>\n[Skočit na zprávu](https://discord.com/channels/%s/%s/%s)", m.Author.Mention(), m.ChannelID, m.GuildID, m.ChannelID, m.ID),
		Color:       0xFFFF00,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Před:", Value: l.truncate(m.BeforeUpdate.Content, 1024), Inline: false},
			{Name: "Po:", Value: l.truncate(m.Content, 1024), Inline: false},
		},
		Timestamp: time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("User ID: %s", m.Author.ID),
		},
	}

	if m.BeforeUpdate != nil && m.BeforeUpdate.Pinned != m.Pinned {
		title := "📌 Zpráva připnuta"
		if !m.Pinned {
			title = "📌 Zpráva odepnuta"
		}
		pinEmbed := &discordgo.MessageEmbed{
			Title:       title,
			Description: fmt.Sprintf("**Autor:** %s\n**Kanál:** <#%s>\n[Skočit na zprávu](https://discord.com/channels/%s/%s/%s)", m.Author.Mention(), m.ChannelID, m.GuildID, m.ChannelID, m.ID),
			Color:       0x3498db,
			Timestamp:   time.Now().Format(time.RFC3339),
		}
		s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, pinEmbed)
	}

	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildMemberAdd(s *discordgo.Session, m *discordgo.GuildMemberAdd) {
	created := l.getCreationTime(m.User.ID)
	age := time.Since(created)
	
	guild, _ := s.State.Guild(m.GuildID)
	memberCount := 0
	if guild != nil {
		memberCount = guild.MemberCount
	}

	embed := &discordgo.MessageEmbed{
		Title:       "📥 Člen se připojil",
		Description: fmt.Sprintf("**Uživatel:** %s (%s)\n**ID:** `%s`", m.User.Mention(), m.User.Username, m.User.ID),
		Color:       0x2ecc71,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Účet vytvořen", Value: l.formatTimestamp(created), Inline: true},
			{Name: "Stáří účtu", Value: l.formatDuration(age), Inline: true},
		},
		Timestamp: time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Celkem členů: %d", memberCount),
		},
	}
	
	if m.User.Bot {
		embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{Name: "Bot", Value: "✅ ANO", Inline: true})
	}

	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)

	/* 
	// Avatar Check log - Disabled as it's redundant with the NSFW worker check
	if l.Config.AvatarLogChannelID != "" {
		avatarEmbed := &discordgo.MessageEmbed{
			Title:       "🖼️ Kontrola avataru",
			Description: fmt.Sprintf("**Uživatel:** %s (%s)\n**ID:** `%s`", m.User.Mention(), m.User.Username, m.User.ID),
			Color:       0x3498db,
			Image: &discordgo.MessageEmbedImage{
				URL: m.User.AvatarURL("1024"),
			},
			Timestamp: time.Now().Format(time.RFC3339),
		}
		s.ChannelMessageSendEmbed(l.Config.AvatarLogChannelID, avatarEmbed)
	}
	*/
}

func (l *Logger) OnGuildMemberRemove(s *discordgo.Session, m *discordgo.GuildMemberRemove) {
	stats.RecordLeave(m.GuildID)
	
	durationStr := "Neznámo"
	joinedAtStr := "Neznámo"
	if m.Member != nil && m.Member.JoinedAt != (time.Time{}) {
		durationStr = l.formatDuration(time.Since(m.Member.JoinedAt))
		joinedAtStr = l.formatTimestamp(m.Member.JoinedAt)
	}

	guild, _ := s.State.Guild(m.GuildID)
	memberCount := 0
	if guild != nil {
		memberCount = guild.MemberCount
	}

	embed := &discordgo.MessageEmbed{
		Title:       "📤 Člen odešel",
		Description: fmt.Sprintf("**Uživatel:** %s (%s)\n**ID:** `%s`", m.User.Mention(), m.User.Username, m.User.ID),
		Color:       0xf1c40f,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Na serveru", Value: durationStr, Inline: true},
			{Name: "Připojil se", Value: joinedAtStr, Inline: true},
		},
		Timestamp: time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("Zbývá členů: %d", memberCount),
		},
	}

	if m.User.Bot {
		embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{Name: "Bot", Value: "✅ ANO", Inline: true})
	}

	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

// Helpers

func (l *Logger) formatDuration(d time.Duration) string {
	days := int(d.Hours()) / 24
	hours := int(d.Hours()) % 24
	minutes := int(d.Minutes()) % 60
	
	if days > 0 {
		return fmt.Sprintf("%d d %d h %d min", days, hours, minutes)
	}
	if hours > 0 {
		return fmt.Sprintf("%d h %d min", hours, minutes)
	}
	return fmt.Sprintf("%d min", minutes)
}

func (l *Logger) formatTimestamp(t time.Time) string {
	// Format: "9. ledna 2026 v 21:12"
	months := []string{"", "ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"}
	return fmt.Sprintf("%d. %s %d v %02d:%02d", t.Day(), months[t.Month()], t.Year(), t.Hour(), t.Minute())
}

func (l *Logger) getCreationTime(id string) time.Time {
	i, err := discordgo.SnowflakeTimestamp(id)
	if err != nil {
		return time.Time{}
	}
	return i
}

func (l *Logger) OnGuildMemberUpdate(s *discordgo.Session, m *discordgo.GuildMemberUpdate) {
	if m.BeforeUpdate == nil {
		return
	}

	// 1. Nickname change
	if m.BeforeUpdate.Nick != m.Nick {
		oldNick := m.BeforeUpdate.Nick
		if oldNick == "" { oldNick = "_[Žádná]_" }
		newNick := m.Nick
		if newNick == "" { newNick = "_[Žádná]_" }

		embed := &discordgo.MessageEmbed{
			Title:       "👤 Člen upraven",
			Description: fmt.Sprintf("**Uživatel:** %s\n**Původní přezdívka:** %s\n**Nová přezdívka:** %s", m.User.Mention(), oldNick, newNick),
			Color:       0x3498db,
			Timestamp:   time.Now().Format(time.RFC3339),
			Footer: &discordgo.MessageEmbedFooter{
				Text: fmt.Sprintf("ID: %s", m.User.ID),
			},
		}
		s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
	}

	// 2. Role change
	if len(m.BeforeUpdate.Roles) != len(m.Roles) {
		added := []string{}
		removed := []string{}
		
		roleMap := make(map[string]bool)
		for _, r := range m.Roles {
			roleMap[r] = true
		}
		
		beforeMap := make(map[string]bool)
		for _, r := range m.BeforeUpdate.Roles {
			beforeMap[r] = true
		}

		for r := range roleMap {
			if !beforeMap[r] {
				added = append(added, fmt.Sprintf("<@&%s>", r))
			}
		}
		for r := range beforeMap {
			if !roleMap[r] {
				removed = append(removed, fmt.Sprintf("<@&%s>", r))
			}
		}

		if len(added) > 0 || len(removed) > 0 {
			embed := &discordgo.MessageEmbed{
				Title:       "⚙️ Člen upraven",
				Description: m.User.Mention(),
				Color:       0x9b59b6,
				Timestamp:   time.Now().Format(time.RFC3339),
				Footer: &discordgo.MessageEmbedFooter{
					Text: fmt.Sprintf("ID: %s", m.User.ID),
				},
			}
			
			if len(added) > 0 {
				embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
					Name: "Přidané role", Value: strings.Join(added, " "), Inline: false,
				})
			}
			if len(removed) > 0 {
				embed.Fields = append(embed.Fields, &discordgo.MessageEmbedField{
					Name: "Odebrané role", Value: strings.Join(removed, " "), Inline: false,
				})
			}

			s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
		}
	}
}

func (l *Logger) OnVoiceStateUpdate(s *discordgo.Session, v *discordgo.VoiceStateUpdate) {
	// Detect Join/Leave/Move
	user, _ := s.User(v.UserID)
	name := v.UserID
	if user != nil {
		name = user.Mention()
	}

	if v.BeforeUpdate == nil {
		if v.ChannelID != "" {
			// Join
			l.sendVoiceLog(s, "🔊 Připojení do Voice", fmt.Sprintf("**Uživatel:** %s\n**Kanál:** <#%s>", name, v.ChannelID), 0x2ecc71)
		}
	} else {
		if v.ChannelID == "" {
			// Leave
			l.sendVoiceLog(s, "🔇 Odpojení z Voice", fmt.Sprintf("**Uživatel:** %s\n**Kanál:** <#%s>", name, v.BeforeUpdate.ChannelID), 0xe74c3c)
		} else if v.BeforeUpdate.ChannelID != v.ChannelID {
			// Move
			l.sendVoiceLog(s, "🔄 Přesun ve Voice", fmt.Sprintf("**Uživatel:** %s\n**Z:** <#%s>\n**Do:** <#%s>", name, v.BeforeUpdate.ChannelID, v.ChannelID), 0x3498db)
		}
	}
}

func (l *Logger) sendVoiceLog(s *discordgo.Session, title, desc string, color int) {
	embed := &discordgo.MessageEmbed{
		Title:       title,
		Description: desc,
		Color:       color,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildBanAdd(s *discordgo.Session, b *discordgo.GuildBanAdd) {
	embed := &discordgo.MessageEmbed{
		Title:       "🔨 Uživatel zabanován",
		Description: fmt.Sprintf("**Uživatel:** %s (%s)\n**ID:** `%s`", b.User.Mention(), b.User.Username, b.User.ID),
		Color:       0x000000,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildBanRemove(s *discordgo.Session, b *discordgo.GuildBanRemove) {
	embed := &discordgo.MessageEmbed{
		Title:       "🔓 Uživatel odbanován",
		Description: fmt.Sprintf("**Uživatel:** %s (%s)\n**ID:** `%s`", b.User.Mention(), b.User.Username, b.User.ID),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnChannelCreate(s *discordgo.Session, c *discordgo.ChannelCreate) {
	embed := &discordgo.MessageEmbed{
		Title:       "🆕 Kanál vytvořen",
		Description: fmt.Sprintf("**Název:** <#%s> (%s)\n**Typ:** %v", c.ID, c.Name, c.Type),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnChannelUpdate(s *discordgo.Session, c *discordgo.ChannelUpdate) {
	embed := &discordgo.MessageEmbed{
		Title:       "⚙️ Kanál upraven",
		Description: fmt.Sprintf("**Kanál:** <#%s>\n**Název:** %s\n**Téma:** %s", c.ID, c.Name, c.Topic),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnChannelDelete(s *discordgo.Session, c *discordgo.ChannelDelete) {
	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Kanál smazán",
		Description: fmt.Sprintf("**Název:** %s\n**ID:** `%s`", c.Name, c.ID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnMessageReactionAdd(s *discordgo.Session, r *discordgo.MessageReactionAdd) {
	if r.UserID == s.State.User.ID {
		return
	}

	user, _ := s.User(r.UserID)
	userName := r.UserID
	if user != nil {
		userName = user.Mention()
	}

	msg, _ := s.ChannelMessage(r.ChannelID, r.MessageID)
	content := "_[Nelze načíst obsah zprávy]_"
	if msg != nil {
		content = l.truncate(msg.Content, 200)
		if content == "" && len(msg.Attachments) > 0 {
			content = "_[Příloha]_"
		}
	}

	embed := &discordgo.MessageEmbed{
		Title:       "👍 Reakce přidána",
		Description: fmt.Sprintf("**Uživatel:** %s\n**Kanál:** <#%s>\n**Reakce:** %s", userName, r.ChannelID, r.Emoji.MessageFormat()),
		Color:       0x34495e,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Zpráva", Value: fmt.Sprintf("[Odkaz](https://discord.com/channels/%s/%s/%s)", r.GuildID, r.ChannelID, r.MessageID), Inline: true},
			{Name: "Obsah zprávy", Value: content, Inline: false},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnInteractionCreate(s *discordgo.Session, i *discordgo.InteractionCreate) {
	if i.Type != discordgo.InteractionApplicationCommand {
		return
	}

	data := i.ApplicationCommandData()
	user := i.Member.User

	params := []string{}
	for _, opt := range data.Options {
		params = append(params, fmt.Sprintf("%s: %v", opt.Name, opt.Value))
	}
	paramStr := strings.Join(params, ", ")
	if paramStr == "" { paramStr = "N/A" }

	embed := &discordgo.MessageEmbed{
		Title:       "⚡ Slash příkaz použit",
		Description: fmt.Sprintf("**Uživatel:** %s\n**Kanál:** <#%s>", user.Mention(), i.ChannelID),
		Color:       0x3498db,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Příkaz", Value: fmt.Sprintf("/%s", data.Name), Inline: true},
			{Name: "Parametry", Value: paramStr, Inline: true},
		},
		Timestamp: time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("ID interakce: %s", i.ID),
		},
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildRoleCreate(s *discordgo.Session, r *discordgo.GuildRoleCreate) {
	embed := &discordgo.MessageEmbed{
		Title:       "⚙️ Role vytvořena",
		Description: fmt.Sprintf("**Název:** <@&%s>\n**ID:** `%s`", r.Role.ID, r.Role.ID),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildRoleUpdate(s *discordgo.Session, r *discordgo.GuildRoleUpdate) {
	// We don't have 'BeforeUpdate' in discordgo for roles easily without state tracking,
	// but we can log that it was updated.
	embed := &discordgo.MessageEmbed{
		Title:       "⚙️ Role upravena",
		Description: fmt.Sprintf("**Role:** <@&%s>\n**Název:** %s\n**Barva:** #%06x", r.Role.ID, r.Role.Name, r.Role.Color),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("ID: %s", r.Role.ID),
		},
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildRoleDelete(s *discordgo.Session, r *discordgo.GuildRoleDelete) {
	embed := &discordgo.MessageEmbed{
		Title:       "⚙️ Role smazána",
		Description: fmt.Sprintf("**ID:** `%s`", r.RoleID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildUpdate(s *discordgo.Session, g *discordgo.GuildUpdate) {
	embed := &discordgo.MessageEmbed{
		Title:       "⚙️ Nastavení serveru upraveno",
		Description: fmt.Sprintf("**Název:** %s\n**Region:** %s\n**Verification Level:** %v", g.Name, g.Region, g.VerificationLevel),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnThreadCreate(s *discordgo.Session, t *discordgo.ThreadCreate) {
	embed := &discordgo.MessageEmbed{
		Title:       "🧵 Vlákno vytvořeno",
		Description: fmt.Sprintf("**Název:** %s\n**Kanál:** <#%s>\n**Tvůrce:** <@%s>", t.Name, t.ParentID, t.OwnerID),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnThreadDelete(s *discordgo.Session, t *discordgo.ThreadDelete) {
	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Vlákno smazáno",
		Description: fmt.Sprintf("**ID:** `%s`", t.ID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnInviteCreate(s *discordgo.Session, i *discordgo.InviteCreate) {
	inviter := "Neznámo"
	if i.Inviter != nil {
		inviter = i.Inviter.Mention()
	}
	embed := &discordgo.MessageEmbed{
		Title:       "📩 Pozvánka vytvořena",
		Description: fmt.Sprintf("**Kód:** `%s`\n**Kanál:** <#%s>\n**Vytvořil:** %s", i.Code, i.ChannelID, inviter),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnInviteDelete(s *discordgo.Session, i *discordgo.InviteDelete) {
	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Pozvánka smazána",
		Description: fmt.Sprintf("**Kód:** `%s`\n**Kanál:** <#%s>", i.Code, i.ChannelID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnAutoModerationActionExecution(s *discordgo.Session, a *discordgo.AutoModerationActionExecution) {
	embed := &discordgo.MessageEmbed{
		Title:       "🛡️ AutoMod Akce",
		Description: fmt.Sprintf("**Uživatel:** <@%s>\n**Pravidlo:** %s\n**Akce:** %v", a.UserID, a.RuleID, a.Action.Type),
		Color:       0xe74c3c,
		Fields: []*discordgo.MessageEmbedField{
			{Name: "Obsah", Value: l.truncate(a.Content, 1024), Inline: false},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.PatternLogChannelID, embed)
}

func (l *Logger) OnAutoModerationRuleCreate(s *discordgo.Session, r *discordgo.AutoModerationRuleCreate) {
	embed := &discordgo.MessageEmbed{
		Title:       "🛡️ AutoMod Pravidlo Vytvořeno",
		Description: fmt.Sprintf("**Název:** %s\n**ID:** `%s`", r.Name, r.ID),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.PatternLogChannelID, embed)
}

func (l *Logger) OnAutoModerationRuleUpdate(s *discordgo.Session, r *discordgo.AutoModerationRuleUpdate) {
	embed := &discordgo.MessageEmbed{
		Title:       "🛡️ AutoMod Pravidlo Upraveno",
		Description: fmt.Sprintf("**Název:** %s\n**ID:** `%s`", r.Name, r.ID),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.PatternLogChannelID, embed)
}

func (l *Logger) OnAutoModerationRuleDelete(s *discordgo.Session, r *discordgo.AutoModerationRuleDelete) {
	embed := &discordgo.MessageEmbed{
		Title:       "🛡️ AutoMod Pravidlo Smazáno",
		Description: fmt.Sprintf("**Název:** %s\n**ID:** `%s`", r.Name, r.ID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.PatternLogChannelID, embed)
}

func (l *Logger) OnMessageDeleteBulk(s *discordgo.Session, m *discordgo.MessageDeleteBulk) {
	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Hromadné mazání zpráv",
		Description: fmt.Sprintf("**Počet smazaných zpráv:** %d\n**Kanál:** <#%s>", len(m.Messages), m.ChannelID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildEmojisUpdate(s *discordgo.Session, e *discordgo.GuildEmojisUpdate) {
	embed := &discordgo.MessageEmbed{
		Title:       "😀 Emoji upraveny",
		Description: fmt.Sprintf("**Počet emoji na serveru:** %d", len(e.Emojis)),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}


func (l *Logger) OnMessageReactionRemove(s *discordgo.Session, r *discordgo.MessageReactionRemove) {
	user, _ := s.User(r.UserID)
	userName := r.UserID
	if user != nil { userName = user.Mention() }
	embed := &discordgo.MessageEmbed{
		Title:       "👎 Reakce odebrána",
		Description: fmt.Sprintf("**Uživatel:** %s\n**Kanál:** <#%s>\n**Reakce:** %s", userName, r.ChannelID, r.Emoji.MessageFormat()),
		Color:       0xe67e22,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnMessageReactionRemoveAll(s *discordgo.Session, r *discordgo.MessageReactionRemoveAll) {
	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Všechny reakce odebrány",
		Description: fmt.Sprintf("**Kanál:** <#%s>\n**Zpráva:** [Odkaz](https://discord.com/channels/%s/%s/%s)", r.ChannelID, r.GuildID, r.ChannelID, r.MessageID),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnWebhooksUpdate(s *discordgo.Session, w *discordgo.WebhooksUpdate) {
	embed := &discordgo.MessageEmbed{
		Title:       "🔗 Webhooky upraveny",
		Description: fmt.Sprintf("**Kanál:** <#%s>", w.ChannelID),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildScheduledEventCreate(s *discordgo.Session, e *discordgo.GuildScheduledEventCreate) {
	embed := &discordgo.MessageEmbed{
		Title:       "📅 Událost vytvořena",
		Description: fmt.Sprintf("**Název:** %s\n**Popis:** %s", e.Name, e.Description),
		Color:       0x2ecc71,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildScheduledEventUpdate(s *discordgo.Session, e *discordgo.GuildScheduledEventUpdate) {
	embed := &discordgo.MessageEmbed{
		Title:       "📅 Událost upravena",
		Description: fmt.Sprintf("**Název:** %s\n**Stav:** %v", e.Name, e.Status),
		Color:       0x3498db,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) OnGuildScheduledEventDelete(s *discordgo.Session, e *discordgo.GuildScheduledEventDelete) {
	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Událost smazána",
		Description: fmt.Sprintf("**Název:** %s", e.Name),
		Color:       0xe74c3c,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
	s.ChannelMessageSendEmbed(l.Config.ServerLogChannelID, embed)
}

func (l *Logger) truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max-3] + "..."
}
