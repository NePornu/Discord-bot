# Příkazy a chování podle modulů

## Core (`bot.py`)
- Start logy do `CONSOLE_CHANNEL_ID` (chunkuje dlouhé zprávy).
- Načítá všechny cogy v `commands/`.
- **Globální check** čte `COMMANDS_CONFIG` (enabled/admin_only).

---

## Logování (`commands/log.py`)
- Dva log kanály (ID jsou v souboru): **MAIN** a **PROFILE**.
- Perzistence: `data/log_config.json` (nastavení), `data/member_cache.json` (cache).
- Slash **group**: `/log`
  - `/log status` – stav, metriky, detaily
  - `/log toggle <typ|all> <true/false>` – granularita (messages/members/channels/roles/voice/…)
  - `/log ignore <channel|user> <id> <add|remove>` – ignorování
  - `/log stats` – statistiky cogu
  - `/log test` – zkušební embed do obou log kanálů

Loguje:
- Členy (join/leave/update, role, timeout, pending…), profily (globálně)
- Kanály (create/update/delete/overwrites), vlákna, role, emoji/stickers
- Invites, webhooks, integrace, stage, scheduled events, reactions
- Moderaci a vybrané audit log akce
- (volitelně) presence změny

---

## Měsíční reporty (`commands/report.py`)
- Automaticky 1. den v měsíci → **report za předchozí měsíc** do `REPORT_CHANNEL_ID`.
- Manuálně: `*report` (na `GUILD_ID`).
- Data:
  - `data/member_counts.json` – joins/leaves po měsících (počítá `on_member_join/remove`)
  - `data/active_users.json` – denní set aktivních userů (počítá `on_message`)
- Metriky: Noví členové, Odchody, Celkem, Průměrné **DAU**, **MAU**, **DAU/MAU%**, Boti/Lidé, Online, počty kanálů/rolí.

---

## Analytika HLL (`activity_hll_optimized.py`)
Příkazy (typicky potřebují `manage_guild`):
- `*dau [days_ago=0]` – DAU pro den
- `*wau` – 7d rolling
- `*mau [window_days=30]` – N-denní rolling (N ≤ retention)
- `*anloghere` – nastav kanál pro heartbeat log
- `*topusers [N]`, `*topchannels [N]` – „dnešní“ heavy-hitters (Space-Saving, RAM only)

Konfigurace v souboru (`CONFIG = { ... }`): `REDIS_URL`, retenční dny, cooldowny, TOP_K atd.

---

## Hromadné DM (`commands/notify.py`) – admin
```
*notify "zpráva" [@role|role_id|ALL] [--skip @uživatel @role 123...]
```
- Posílá DM **velmi opatrně** (90±30 s mezi uživateli, concurrency=1, retry).
- Výsledky v CSV jako příloha do `CONSOLE_CHANNEL_ID`.
- `DRY_RUN = True` → jen simulace.

---

## Verifikace (`commands/verification.py`)
- Při joinu:
  - přidá ověřovací roli,
  - pošle DM s kódem,
  - čeká na odpověď,
  - moderátor potvrdí tlačítkem v `MOD_CHANNEL_ID`.
- Po ověření: DM „Vítej“ + uvítací zpráva do `WELCOME_CHANNEL_ID`.

---

## Čištění (`commands/purge.py`) – manage_messages
```
*purge <množství 1–100> [@uživatel] [slovo]
```
- Najde přesně N odpovídajících zpráv (prochází až ~1000), hromadně smaže.

---

## Status embedy (`commands/status.py`) – manage_messages
```
*status [kód|stav] [služba] (podrobnosti)
```
- Kódy `1..11` mapují na stavy (online/údržba/výpadek/…).
- Mazání příkazové zprávy, cooldown, hezký barevný embed.

---

## Emoji Challenge (`commands/emojirole.py`) – admin
Automatický systém odměn za poslání správné kombinace emoji v určeném kanále.

### Nastavení
**Slash příkazy** (`/challenge`):
```
/challenge setup role:@Role channel_name:<#kanál> emojis:"🍁 :strongdoge: 🔥"
/challenge show                    – zobrazí aktuální konfiguraci
/challenge settings                – nastavení chování (react_ok, reply_on_success, require_all)
/challenge messages add text:"..."  – přidá vlastní zprávu pro úspěch
/challenge messages list           – seznam všech zpráv
/challenge messages clear          – smaže všechny zprávy
/challenge clear                   – smaže celou konfiguraci
```

**Prefix příkazy** (`*challenge`):
```
*challenge setup role:@Role channel_name:<#kanál> emojis:"🍁 :strongdoge: 🔥"
*challenge show
*challenge messages add text:"Vítej!"
*challenge messages list
*challenge messages clear
*challenge clear
```

### Chování
- **Úspěšná kombinace**:
  - Bot zareaguje ✅
  - Přidá roli uživateli (pokud ji ještě nemá)
  - Odpoví náhodnou zprávou z 30 přednastavených (nebo vlastních)
  
- **Ostatní zprávy**: Bot je tiché ignoruje (žádná reakce, žádná odpověď)

### Formát emoji
- **Unicode emoji**: `🍁 🔥 💪`
- **Custom emoji**: `:strongdoge:` nebo `<:strongdoge:123456789>`
- **Kombinované**: `🍁 :strongdoge: 🔥`

### Nastavení
- `require_all: true` – musí obsahovat všechna emoji (výchozí)
- `require_all: false` – stačí alespoň jedno emoji
- `react_ok: true` – reaguje checkmarkem na úspěch
- `reply_on_success: true` – posílá náhodnou zprávu

### Datové soubory
- `data/challenge_config.json` – konfigurace per guild (role, kanál, emoji, zprávy)

### Přednastavené zprávy (30)
Při úspěšné kombinaci bot vybere náhodně z těchto zpráv:
- Vítej ve výzvě! ✅
- Gratuluji, máš to! 🔥
- Achievement unlocked! 🏅
- Beast mode activated! 🐺
- Level up! 📈
- ... a dalších 25 variací

---


## Výzvy (`commands/vyzva.py`) – admin
```
*vyhodnotit_vyzvu [#kanál|-] [vypis=true/false] [filtr|photo|-]
                   [mode=days/fotosum/weekly] [interval]
                   [počet role] [počet role] ...
```
- **days** – počet dní s aktivitou
- **fotosum** – počet příspěvků s fotkou (vyžaduje filtr `photo`)
- **weekly** – po sobě jdoucí X-denní intervaly s aktivitou
- Může **přidělovat role** po dosažení prahů.
