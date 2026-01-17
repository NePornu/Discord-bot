# Dashboard Secrets & Configuration

# Flask Session Security - MUST BE STATIC for session persistence
SECRET_KEY = "xK9mP2vL5nR8qT4wY7aB0cD3eF6gH1iJ"  # Static key for sessions
ACCESS_TOKEN = "dashboard_access_token_2024"
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

# Discord OAuth2
DISCORD_CLIENT_ID = "1462004084302151814"
DISCORD_CLIENT_SECRET = "rev1v2dVMB-3g-Ho7DzMeY3-CXYIjFCf"
DISCORD_REDIRECT_URI = "http://207.180.223.191:8092/auth/callback"

# Admin Discord User IDs (get full access)
ADMIN_USER_IDS = []  # Add your Discord user ID here for admin access
