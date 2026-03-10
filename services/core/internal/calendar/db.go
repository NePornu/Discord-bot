package calendar

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"

	"github.com/redis/go-redis/v9"
)

type Calendar struct {
	ID            int    `json:"id"`
	MessageID     string `json:"message_id"`
	ChannelID     string `json:"channel_id"`
	Name          string `json:"name"`
	StartDate     string `json:"start_date"`
	NumDays       int    `json:"num_days"`
	TestMode      bool   `json:"test_mode"`
	BroadcastDays int    `json:"broadcast_days"`
	LastBroadcast string `json:"last_broadcast"`
}

type Day struct {
	ID          int    `json:"id"`
	CalendarID  int    `json:"calendar_id"`
	DayNum      int    `json:"day"`
	Title       string `json:"title"`
	Emoji       string `json:"emoji"`
	BtnLabel    string `json:"btn_label"`
	BtnEmoji    string `json:"btn_emoji"`
	RewardText  string `json:"reward_text"`
	RewardLink  string `json:"reward_link"`
	RewardImage string `json:"reward_image"`
	RewardRole  string `json:"reward_role"`
}

type CalendarDB struct {
	redis *redis.Client
	ctx   context.Context
}

func NewCalendarDB(client *redis.Client) *CalendarDB {
	return &CalendarDB{
		redis: client,
		ctx:   context.Background(),
	}
}

func (c *CalendarDB) GetCalendar(id int) (*Calendar, error) {
	data, err := c.redis.Get(c.ctx, fmt.Sprintf("calendar:%d", id)).Result()
	if err != nil {
		return nil, err
	}
	var cal Calendar
	if err := json.Unmarshal([]byte(data), &cal); err != nil {
		return nil, err
	}
	return &cal, nil
}

func (c *CalendarDB) GetDay(calendarID, dayNum int) (*Day, error) {
	data, err := c.redis.Get(c.ctx, fmt.Sprintf("calendar:%d:day:%d", calendarID, dayNum)).Result()
	if err != nil {
		return nil, err
	}
	var d Day
	if err := json.Unmarshal([]byte(data), &d); err != nil {
		return nil, err
	}
	return &d, nil
}

func (c *CalendarDB) IsClaimed(calendarID, dayNum int, userID string) bool {
	res, _ := c.redis.SIsMember(c.ctx, fmt.Sprintf("calendar:%d:claims:%d", calendarID, dayNum), userID).Result()
	return res
}

func (c *CalendarDB) SaveClaim(calendarID, dayNum int, userID string) error {
	return c.redis.SAdd(c.ctx, fmt.Sprintf("calendar:%d:claims:%d", calendarID, dayNum), userID).Err()
}

func (c *CalendarDB) ListActiveCalendars() ([]*Calendar, error) {
	ids, err := c.redis.SMembers(c.ctx, "calendars:list").Result()
	if err != nil {
		return nil, err
	}

	var cals []*Calendar
	for _, idStr := range ids {
		id, _ := strconv.Atoi(idStr)
		cal, err := c.GetCalendar(id)
		if err == nil {
			cals = append(cals, cal)
		}
	}
	return cals, nil
}

func (c *CalendarDB) ListDays(calendarID int) ([]*Day, error) {
	// In Redis we might store keys for days in a sorted set or just iterate
	var days []*Day
	for i := 1; i <= 31; i++ {
		d, err := c.GetDay(calendarID, i)
		if err == nil {
			days = append(days, d)
		}
	}
	return days, nil
}
