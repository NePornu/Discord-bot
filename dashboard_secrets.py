# Dashboard Secrets & Configuration

# Flask Session Security
import secrets
SECRET_KEY = secrets.token_urlsafe(32)
ACCESS_TOKEN = secrets.token_urlsafe(32)
SESSION_EXPIRY_HOURS = 24

# SMTP Configuration (Gmail/Google Workspace)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "marcipan@nepornu.cz"
SMTP_PASSWORD = "bqys izzp mfjl ckdd"  # App Password
SMTP_FROM = "NePornu Dashboard <marcipan@nepornu.cz>"

# OTP Rules
ALLOWED_EMAIL_DOMAIN = "@nepornu.cz"
OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_RATE_LIMIT = 3
