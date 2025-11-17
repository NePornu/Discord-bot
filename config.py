# Nastavení pro bot a moduly
BOT_PREFIX = "*"  # Prefix pro příkazy
GUILD_ID = 615171377783242769  # ID serveru (guild)
MOD_CHANNEL_ID = 1351911780892409958
LOG_CHANNEL_ID = 1351911780892409958  # ID kanálu pro moderátory
WELCOME_CHANNEL_ID = 1351911916305514506  # ID kanálu pro logování

COMMANDS_CONFIG = {
    "ping": {"enabled": True, "admin_only": False},
    "reverify_all": {"enabled": True, "admin_only": False},
    "echo": {"enabled": True, "admin_only": True},  # Pouze admini mohou použít echo
    # Přidávejte další příkazy zde
}
