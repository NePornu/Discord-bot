
BOT_PREFIX = "*"  


import os
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


GUILD_ID = 615171377783242769  
MOD_CHANNEL_ID = 1351911780892409958
VERIFICATION_CHANNEL_ID = 1459269521440506110  
VERIFICATION_LOG_CHANNEL_ID = 1351911780892409958  
PROFILE_LOG_CHANNEL_ID = 1351911780892410003
LOG_CHANNEL_ID = 1351911780892409958  
WELCOME_CHANNEL_ID = 1351911916305514506  
CONSOLE_CHANNEL_ID = 1245571689178464257
REPORT_CHANNEL_ID = 1425752839820677130


VERIFICATION_CODE = 'Restart'  
VERIFIED_ROLE_ID = 1179506149951811734  


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
