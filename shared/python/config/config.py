
BOT_PREFIX = "*"  

import os

# Helper to load int from env or default
def get_env_int(name, default):
    val = os.getenv(name)
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    return default

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN")

GUILD_ID = get_env_int("GUILD_ID", 615171377783242769)
MOD_CHANNEL_ID = get_env_int("MOD_CHANNEL_ID", 1351911780892409958)
VERIFICATION_CHANNEL_ID = get_env_int("VERIFICATION_CHANNEL_ID", 1459269521440506110)
VERIFICATION_LOG_CHANNEL_ID = get_env_int("VERIFICATION_LOG_CHANNEL_ID", 1351911780892409958)
PROFILE_LOG_CHANNEL_ID = get_env_int("PROFILE_LOG_CHANNEL_ID", 1404734262485450772)
LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID", 1404416148077809705)
WELCOME_CHANNEL_ID = get_env_int("WELCOME_CHANNEL_ID", 1351911916305514506)
CONSOLE_CHANNEL_ID = get_env_int("CONSOLE_CHANNEL_ID", 1245571689178464257)
REPORT_CHANNEL_ID = get_env_int("REPORT_CHANNEL_ID", 1425752839820677130)
NSFW_ALERT_CHANNEL_ID = get_env_int("ALERT_CHANNEL_ID", 1468607459332456518)
NSFW_LOG_CHANNEL_ID = get_env_int("NSFW_LOG_CHANNEL_ID", 1404416148077809705)
NSFW_THRESHOLD = float(os.getenv("NSFW_THRESHOLD", "0.5"))

VERIFICATION_CODE = os.getenv("VERIFICATION_CODE", 'Restart')
VERIFIED_ROLE_ID = get_env_int("VERIFIED_ROLE_ID", 1179506149951811734)
WAITING_ROLE_ID = get_env_int("WAITING_ROLE_ID", 1179506149951811734) # Sync with Go

# --- Pattern Detection ---
PATTERN_ALERT_CHANNEL_ID = get_env_int("PATTERN_LOG_CHANNEL_ID", 1484271428567302154)
PATTERN_SCAN_INTERVAL_MINUTES = get_env_int("PATTERN_SCAN_INTERVAL_MINUTES", 15)
PATTERN_ALERT_COOLDOWN_HOURS = get_env_int("PATTERN_ALERT_COOLDOWN_HOURS", 24)
DIARY_CHANNEL_NAMES = ["denik-abstinence", "deník", "diary", "můj-deník"]

# --- Quest / Challenge ---
QUEST_CHANNEL_ID = get_env_int("QUEST_CHANNEL_ID", 0) or None
CHALLENGE_START_DATE = os.getenv("CHALLENGE_START_DATE", "20260210")
CHALLENGE_END_DATE = os.getenv("CHALLENGE_END_DATE", "20260310")
HABIT_ROLES = {}

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
    "help": {"enabled": True, "admin_only": True},
    "nsfwsync": {"enabled": True, "admin_only": True},
    "quest_stats": {"enabled": True, "admin_only": False},
    "quest_backfill": {"enabled": True, "admin_only": True}
}
