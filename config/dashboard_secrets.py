import os

# Dashboard Secrets & Configuration

# Flask Session Security - MUST BE STATIC for session persistence
SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY")
ACCESS_TOKEN = os.getenv("DASHBOARD_ACCESS_TOKEN")
SESSION_EXPIRY_HOURS = 24

# SMTP Configuration (Gmail/Google Workspace)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "marcipan@nepornu.cz"
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # App Password via Env
SMTP_FROM = "NePornu Dashboard <marcipan@nepornu.cz>"

# OTP Rules
ALLOWED_EMAIL_DOMAIN = "@nepornu.cz"
OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_RATE_LIMIT = 3

# Discord OAuth2
DISCORD_CLIENT_ID = "1462004084302151814"
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = "http://207.180.223.191:8092/auth/callback"

# Admin Discord User IDs (get full access)
ADMIN_USER_IDS = [471218810964410368]  # MarciPan
BOT_TOKEN = os.getenv("BOT_TOKEN")
