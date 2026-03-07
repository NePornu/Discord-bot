package calendar

import (
	"database/sql"
	"os"

	_ "github.com/mattn/go-sqlite3"
)

type Calendar struct {
	ID            int
	MessageID     string
	ChannelID     string
	Name          string
	StartDate     string
	NumDays       int
	TestMode      bool
	BroadcastDays int
	LastBroadcast sql.NullString
}

type Day struct {
	ID          int
	CalendarID  int
	DayNum      int
	Title       string
	Emoji       string
	BtnLabel    string
	BtnEmoji    string
	RewardText  string
	RewardLink  string
	RewardImage string
	RewardRole  string
}

type CalendarDB struct {
	db *sql.DB
}

func NewCalendarDB(path string) (*CalendarDB, error) {
	if _, err := os.Stat("data"); os.IsNotExist(err) {
		os.Mkdir("data", 0755)
	}

	db, err := sql.Open("sqlite3", path)
	if err != nil {
		return nil, err
	}

	c := &CalendarDB{db: db}
	if err := c.Init(); err != nil {
		return nil, err
	}

	return c, nil
}

func (c *CalendarDB) Init() error {
	queries := []string{
		`CREATE TABLE IF NOT EXISTS calendars (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			message_id TEXT,
			channel_id TEXT,
			name TEXT,
			start_date TEXT,
			num_days INTEGER,
			test_mode INTEGER DEFAULT 0,
			broadcast_days INTEGER DEFAULT 0,
			last_broadcast TEXT
		)`,
		`CREATE TABLE IF NOT EXISTS days (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			calendar_id INTEGER,
			day INTEGER,
			title TEXT,
			emoji TEXT,
			btn_label TEXT,
			btn_emoji TEXT,
			reward_text TEXT,
			reward_link TEXT,
			reward_image TEXT,
			reward_role TEXT,
			UNIQUE(calendar_id, day)
		)`,
		`CREATE TABLE IF NOT EXISTS claims (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			calendar_id INTEGER,
			day INTEGER,
			user TEXT,
			UNIQUE(calendar_id, day, user)
		)`,
	}

	for _, q := range queries {
		if _, err := c.db.Exec(q); err != nil {
			return err
		}
	}
	return nil
}

func (c *CalendarDB) GetCalendar(id int) (*Calendar, error) {
	row := c.db.QueryRow("SELECT id, message_id, channel_id, name, start_date, num_days, test_mode, broadcast_days, last_broadcast FROM calendars WHERE id = ?", id)
	cal := &Calendar{}
	err := row.Scan(&cal.ID, &cal.MessageID, &cal.ChannelID, &cal.Name, &cal.StartDate, &cal.NumDays, &cal.TestMode, &cal.BroadcastDays, &cal.LastBroadcast)
	if err != nil {
		return nil, err
	}
	return cal, nil
}

func (c *CalendarDB) GetDay(calendarID, dayNum int) (*Day, error) {
	row := c.db.QueryRow("SELECT id, calendar_id, day, title, emoji, btn_label, btn_emoji, reward_text, reward_link, reward_image, reward_role FROM days WHERE calendar_id = ? AND day = ?", calendarID, dayNum)
	d := &Day{}
	err := row.Scan(&d.ID, &d.CalendarID, &d.DayNum, &d.Title, &d.Emoji, &d.BtnLabel, &d.BtnEmoji, &d.RewardText, &d.RewardLink, &d.RewardImage, &d.RewardRole)
	if err != nil {
		return nil, err
	}
	return d, nil
}

func (c *CalendarDB) IsClaimed(calendarID, dayNum int, userID string) bool {
	var id int
	err := c.db.QueryRow("SELECT id FROM claims WHERE calendar_id = ? AND day = ? AND user = ?", calendarID, dayNum, userID).Scan(&id)
	return err == nil
}

func (c *CalendarDB) SaveClaim(calendarID, dayNum int, userID string) error {
	_, err := c.db.Exec("INSERT INTO claims (calendar_id, day, user) VALUES (?, ?, ?)", calendarID, dayNum, userID)
	return err
}

func (c *CalendarDB) ListActiveCalendars() ([]*Calendar, error) {
	rows, err := c.db.Query("SELECT id, message_id, channel_id, name, start_date, num_days, test_mode, broadcast_days, last_broadcast FROM calendars ORDER BY id DESC")
	if err != nil { return nil, err }
	defer rows.Close()

	var cals []*Calendar
	for rows.Next() {
		cal := &Calendar{}
		rows.Scan(&cal.ID, &cal.MessageID, &cal.ChannelID, &cal.Name, &cal.StartDate, &cal.NumDays, &cal.TestMode, &cal.BroadcastDays, &cal.LastBroadcast)
		cals = append(cals, cal)
	}
	return cals, nil
}

func (c *CalendarDB) ListDays(calendarID int) ([]*Day, error) {
	rows, err := c.db.Query("SELECT id, calendar_id, day, title, emoji, btn_label, btn_emoji FROM days WHERE calendar_id = ? ORDER BY day", calendarID)
	if err != nil { return nil, err }
	defer rows.Close()

	var days []*Day
	for rows.Next() {
		d := &Day{}
		rows.Scan(&d.ID, &d.CalendarID, &d.DayNum, &d.Title, &d.Emoji, &d.BtnLabel, &d.BtnEmoji)
		days = append(days, d)
	}
	return days, nil
}
