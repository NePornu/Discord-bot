# Nastavení pro bot a moduly
BOT_PREFIX = "*"  # Prefix pro příkazy

# Redis Configuration
REDIS_URL = "redis://redis-hll:6379/0"

# Guild & Channel IDs
GUILD_ID = 615171377783242769  # ID serveru (guild)
MOD_CHANNEL_ID = 1351911780892409958
VERIFICATION_CHANNEL_ID = 1459269521440506110  # Schvalovací zprávy s tlačítky
VERIFICATION_LOG_CHANNEL_ID = 1351911780892409958  # Detailní logy
PROFILE_LOG_CHANNEL_ID = 1351911780892410003
LOG_CHANNEL_ID = 1351911780892409958  # ID kanálu pro moderátory
WELCOME_CHANNEL_ID = 1351911916305514506  # ID kanálu pro logování
CONSOLE_CHANNEL_ID = 1245571689178464257
REPORT_CHANNEL_ID = 1425752839820677130

# Verification Settings (merged from verification_config.py)
VERIFICATION_CODE = 'Restart'  # Ověřovací kód
VERIFIED_ROLE_ID = 1179506149951811734  # ID ověřovací role

# Command Configuration
COMMANDS_CONFIG = {
    "ping": {"enabled": True, "admin_only": False},
    "echo": {"enabled": True, "admin_only": True},
    "reverify_all": {"enabled": True, "admin_only": True},
    "purge": {"enabled": True, "admin_only": True},
    "vyhodnotit_vyzvu": {"enabled": True, "admin_only": True},
    "status": {"enabled": True, "admin_only": True},
    "report": {"enabled": True, "admin_only": True},
    "notify": {"enabled": True, "admin_only": True},
    "emojirole": {"enabled": True, "admin_only": True},
    "help": {"enabled": True, "admin_only": True}
}
