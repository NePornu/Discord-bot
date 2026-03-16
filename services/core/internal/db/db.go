package db

import (
	"database/sql"
	"log/slog"
	"time"

	_ "github.com/lib/pq"
)

var DB *sql.DB

func Init(connStr string) error {
	var err error
	DB, err = sql.Open("postgres", connStr)
	if err != nil {
		return err
	}

	// Set connection pool settings
	DB.SetMaxOpenConns(25)
	DB.SetMaxIdleConns(5)
	DB.SetConnMaxLifetime(5 * time.Minute)

	// Verify connection
	err = DB.Ping()
	if err != nil {
		return err
	}

	slog.Info("PostgreSQL connected successfully")
	return nil
}

func Close() {
	if DB != nil {
		DB.Close()
	}
}
