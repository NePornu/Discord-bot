package logging

import (
	"fmt"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
)

type Logger struct {
	Config *config.Config
}

func NewLogger(cfg *config.Config) *Logger {
	return &Logger{Config: cfg}
}

func (l *Logger) OnMessageDelete(s *discordgo.Session, m *discordgo.MessageDelete) {
	// For Delete, we MUST check State
	oldMsg, err := s.State.Message(m.ChannelID, m.ID)
	if err != nil || oldMsg == nil || oldMsg.Author == nil {
		return
	}

	content := oldMsg.Content
	if content == "" {
		content = "_[Žádný textový obsah]_"
	}

	embed := &discordgo.MessageEmbed{
		Title:       "🗑️ Zpráva smazána",
		Description: fmt.Sprintf("**Autor:** %s\n**Kanál:** <#%s>\n\n**Obsah:**\n%s", oldMsg.Author.Mention(), m.ChannelID, content),
		Color:       0xFF0000,
		Timestamp:   time.Now().Format(time.RFC3339),
		Footer: &discordgo.MessageEmbedFooter{
			Text: fmt.Sprintf("User ID: %s", oldMsg.Author.ID),
		},
	}

	s.ChannelMessageSendEmbed(l.Config.AlertChannelID, embed)
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
	}

	s.ChannelMessageSendEmbed(l.Config.AlertChannelID, embed)
}

func (l *Logger) OnGuildMemberAdd(s *discordgo.Session, m *discordgo.GuildMemberAdd) {
	// Detailed join log is handled by verification service
}

func (l *Logger) OnGuildMemberRemove(s *discordgo.Session, m *discordgo.GuildMemberRemove) {
	msg := fmt.Sprintf("📤 **%s** (%s) opustil/a server.", m.User.Username, m.User.ID)
	logChannel := l.Config.WaitLogChannelID

	// Send to Log channel
	s.ChannelMessageSend(logChannel, msg)
}

func (l *Logger) truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max-3] + "..."
}
