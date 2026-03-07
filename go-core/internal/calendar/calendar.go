package calendar

import (
	"fmt"
	"log"
	"strconv"
	"strings"
	"time"

	"github.com/bwmarrin/discordgo"
	"github.com/nepornucz/discord-bot-core/internal/config"
)

type CalendarService struct {
	Config *config.Config
	DB     *CalendarDB
}

func NewCalendarService(cfg *config.Config) *CalendarService {
	db, err := NewCalendarDB("data/calendar.db")
	if err != nil {
		log.Fatalf("Failed to initialize calendar DB: %v", err)
	}
	return &CalendarService{
		Config: cfg,
		DB:     db,
	}
}

func (s *CalendarService) HandleInteraction(dg *discordgo.Session, i *discordgo.InteractionCreate) {
	data := i.MessageComponentData()
	customID := data.CustomID

	if strings.HasPrefix(customID, "pub_cal:") {
		s.handleClaim(dg, i, customID)
	}
}

func (s *CalendarService) handleClaim(dg *discordgo.Session, i *discordgo.InteractionCreate, customID string) {
	parts := strings.Split(customID, ":")
	if len(parts) < 3 { return }
	
	calID, _ := strconv.Atoi(parts[1])
	dayNum, _ := strconv.Atoi(parts[2])

	cal, err := s.DB.GetCalendar(calID)
	if err != nil {
		dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: "❌ Kalendář nenalezen.", Flags: 64},
		})
		return
	}

	// Check date
	startDate, _ := time.Parse("2006-01-02", cal.StartDate)
	targetDate := startDate.AddDate(0, 0, dayNum-1)
	now := time.Now()

	if !cal.TestMode && now.Before(targetDate) {
		dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{
				Content: fmt.Sprintf("⏳ Otevření je možné až **%s**.", targetDate.Format("02.01.2006")),
				Flags: 64,
			},
		})
		return
	}

	if s.DB.IsClaimed(calID, dayNum, i.Member.User.ID) {
		dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
			Type: discordgo.InteractionResponseChannelMessageWithSource,
			Data: &discordgo.InteractionResponseData{Content: "❌ Toto okénko jsi už otevřel/a!", Flags: 64},
		})
		return
	}

	day, err := s.DB.GetDay(calID, dayNum)
	if err != nil { return }

	if err := s.DB.SaveClaim(calID, dayNum, i.Member.User.ID); err != nil { return }

	// Reward delivery
	content := fmt.Sprintf("🎄 **Den %d: %s**\n\n%s", dayNum, day.Title, day.RewardText)
	if day.RewardLink != "" {
		content += fmt.Sprintf("\n🔗 %s", day.RewardLink)
	}

	if day.RewardRole != "" {
		dg.GuildMemberRoleAdd(i.GuildID, i.Member.User.ID, day.RewardRole)
		content += "\n✅ Získal jsi roli!"
	}

	// Send DM
	ch, err := dg.UserChannelCreate(i.Member.User.ID)
	if err == nil {
		dg.ChannelMessageSend(ch.ID, content)
	}

	dg.InteractionRespond(i.Interaction, &discordgo.InteractionResponse{
		Type: discordgo.InteractionResponseChannelMessageWithSource,
		Data: &discordgo.InteractionResponseData{Content: "🎁 Odměna odeslána do DM!", Flags: 64},
	})
}
