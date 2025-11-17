# Logování serveru

- Dva kanály (natvrdo v `commands/log.py`):
  - **CHANNEL_MAIN_LOG_ID** – hlavní dění (kanály, role, moderace, zprávy…)
  - **CHANNEL_PROFILE_LOG_ID** – profilové změny (jména, avataři, globální změny)
- Nastavení per-guild se ukládá do `data/log_config.json`.

## Slash /log
- `/log status` – přehled a metriky (uptime, fronta, cache členů…).
- `/log toggle` – zap/vyp jednotlivé oblasti: messages, members, channels, roles, voice, moderation, reactions, invites, threads, webhooks, emojis, stickers, integrations, automod, applications, presence.
- `/log ignore` – přidá/odebere **kanál** nebo **uživatele** z ignorování.
- `/log stats` – stručné statistiky cogu.
- `/log test` – pošle testovací zprávy do obou log kanálů.

## Perzistence
- `data/log_config.json` – volby
- `data/member_cache.json` – cache informací o členech (urychluje profilové diffy)
