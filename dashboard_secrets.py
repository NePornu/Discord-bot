# Dashboard Security Configuration
# KEEP THIS FILE SECRET - DO NOT COMMIT TO GIT

# Session Secret (for cookie signing)
SECRET_KEY = "O5x8vQgZKzB_7wmFfEh3YPRqN2jLdA9uT6iC1sXkMpH"

# BACKUP: Emergency access token (for /emergency-login route)
EMERGENCY_TOKEN = "hR4wJ8nK2pY6xV9mQ3sT7dF1gL5cB0zA"

# Email OTP Configuration
ALLOWED_EMAIL_DOMAIN = "@nepornu.cz"

# SMTP Configuration (for sending OTP emails)
SMTP_HOST = "smtp.gmail.com"  # or your SMTP server
SMTP_PORT = 587
SMTP_USER = "your-email@nepornu.cz"  # UPDATE THIS
SMTP_PASSWORD = "your-app-password"   # UPDATE THIS (Gmail App Password)
SMTP_FROM = "NePornu Dashboard <noreply@nepornu.cz>"

# Session expiration (hours)
SESSION_EXPIRY_HOURS = 24

# OTP Settings
OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 300  # 5 minutes
OTP_MAX_ATTEMPTS = 5
OTP_RATE_LIMIT = 3  # Max OTP requests per 10 minutes
