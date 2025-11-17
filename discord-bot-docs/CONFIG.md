# Konfigurace a oprávnění

## Soubor `config.py`
Klíčové hodnoty (příklad):

```py
BOT_PREFIX = "*"

GUILD_ID = 615171377783242769
MOD_CHANNEL_ID = 1351911780892409958
LOG_CHANNEL_ID = 1351911780892409958
WELCOME_CHANNEL_ID = 1351911916305514506
CONSOLE_CHANNEL_ID = 1245571689178464257
REPORT_CHANNEL_ID = 1425752839820677130

COMMANDS_CONFIG = {
  "ping": {"enabled": True, "admin_only": False},
  "echo": {"enabled": True, "admin_only": True},
  "reverify_all": {"enabled": True, "admin_only": True},
  "purge": {"enabled": True, "admin_only": True},
  "vyhodnotit_vyzvu": {"enabled": True, "admin_only": True},
  "status": {"enabled": True, "admin_only": True},
  "report": {"enabled": True, "admin_only": True},
  "notify": {"enabled": True, "admin_only": True}
}
```

- **BOT_PREFIX** – prefix příkazů (default `*`).
- **GUILD_ID** – hlavní server.
- **…_CHANNEL_ID** – kanály pro logy/uvítání/reporty/konzoli.
- **COMMANDS_CONFIG** – centrální povolení příkazů a **admin_only**.

> V `bot.py` běží **globální check**: čte právě `COMMANDS_CONFIG`. Pokud je příkaz zakázaný, nepustí se. Pokud je `admin_only`, smí ho jen administrátoři.

## `verification_config.py`
```py
VERIFICATION_CODE = "Restart"
VERIFIED_ROLE_ID = 1179506149951811734
```
- **VERIFICATION_CODE** – kód pro DM ověření.
- **VERIFIED_ROLE_ID** – role, kterou při ověřování bot spravuje.

## Token
V souboru `bot_token.py` očekáváme proměnnou:
```py
TOKEN = "tvůj_discord_token"
```

## Oprávnění a Intents
V **Discord Developer Portal → Bot** zapni:
- ✅ Server Members Intent
- ✅ Message Content Intent
- (volitelně) ✅ Presence Intent

Při pozvání bota dej minimálně: *View Channels*, *Send Messages*, *Embed Links*, *Attach Files*.  
Pro příkazy, které pracují se zprávami/rolemi: *Manage Messages*, *Manage Roles*.
