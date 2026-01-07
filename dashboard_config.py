# Ultimate Discord Bot Dashboard - Environment Configuration

# Discord Bot Token
TOKEN = "YOUR_BOT_TOKEN_HERE"  # Already configured

# Discord OAuth2 Configuration (for dashboard authentication)
DISCORD_CLIENT_ID = "YOUR_CLIENT_ID"
DISCORD_CLIENT_SECRET = "YOUR_CLIENT_SECRET"
DISCORD_REDIRECT_URI = "http://discord.nepornu.cz/callback"

# Guild Configuration
TARGET_GUILD_ID = 615171377783242769  # NePornu server

# Session Secret (generate with: python -c "import secrets; print(secrets.token_urlsafe(32))")
SESSION_SECRET = "CHANGE_THIS_TO_RANDOM_STRING"

# Redis Configuration
REDIS_HOST = "172.22.0.2"
REDIS_PORT = 6379
REDIS_DB = 0
