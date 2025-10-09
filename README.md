# 🤖 Discord Bot – Kompletní dokumentace

Tento bot je **modulární, rozšiřitelný systém** postavený na **Discord.py (v2.3+)** s využitím **Cogů**, zaměřený na:
- správu serveru (logování, verifikace, reporty),
- analytiku (DAU/MAU, Redis HLL),
- automatizaci (notifikace, výzvy, statusy),
- bezpečný a přehledný provoz (konfigurace, systemd, Docker).

---

## 🧱 Struktura projektu

```
📁 bot/
 ├── bot.py                → hlavní běh bota (načítá cogy, prefix, eventy)
 ├── config.py             → konfigurace ID serverů, kanálů, příkazů
 ├── bot_token.py          → discord token (ignorovat v Gitu)
 ├── verification_config.py → nastavení ověřování
 ├── /commands             → všechny cogy (moduly)
 │   ├── log.py            → logování událostí
 │   ├── report.py         → měsíční reporty
 │   ├── notify.py         → hromadné DM
 │   ├── purge.py          → čištění kanálů
 │   ├── verification.py   → ověřování uživatelů
 │   ├── status.py         → stavové embedy
 │   ├── vyzva.py          → challenge systém
 │   └── emojirole.py      → emoji role handler
 ├── /data                 → runtime data (json, cache)
 ├── /analytics            → HLL analytika, Redis
 ├── /logs                 → výstupy /log příkazů
 └── requirements.txt
```

---

## ⚙️ Funkce

### 📈 Analytika a reporty
- Denní / měsíční reporty (DAU/MAU, nové členy, online stav)
- Redis HLL → unikátní uživatelé a heavy-hitters
- `/report` → generuje embed se statistikami
- Automaticky se spouští 1. den v měsíci 00:05 UTC

### 🔒 Moderace a správa
- `*purge`, `*status`, `*notify`, `*vyzva`
- `/log` systém (kanály, role, členové, moderace, automod)
- Auditní embedy v reálném čase
- Verifikační systém přes DM

### 🧠 Inteligentní design
- Každý modul je samostatný *Cog* s vlastním lifecyclem
- Konfigurace příkazů (`enabled`, `admin_only`) v `config.py`
- Log kanály a report kanál nastavitelné z jednoho místa

---

## 🧰 Nasazení

### Lokálně (venv)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

### Systemd
```bash
sudo systemctl enable --now discord-bot
journalctl -u discord-bot -f
```

### Docker
```bash
docker build -t discord-bot .
docker run --name discord-bot   -v $(pwd)/data:/app/data   --restart unless-stopped   discord-bot
```

### Docker Compose (doporučeno)
Společný běh bota + Redis:
```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    depends_on:
      - redis
    volumes:
      - ./data:/app/data
  redis:
    image: redis:7
    restart: unless-stopped
```

---

## 📊 Datové výstupy

| Soubor | Účel |
|--------|------|
| `member_counts.json` | měsíční join/leave statistiky |
| `active_users.json` | denní aktivní uživatelé |
| `log_config.json` | konfigurace logů |
| `member_cache.json` | cache profilů |
| `redis (HLL)` | unikátní DAU/WAU/MAU, heavy-hitters |

---

## 🔐 Bezpečnost
- Token nikdy necommituješ (soubor `bot_token.py` ignorovaný v `.gitignore`).
- Minimální oprávnění.
- Safe rate-limity (např. notify má intervaly 90±30 s).
- Oddělený systémový uživatel a přístup jen k potřebným kanálům.

---

## 🧩 Rozšíření
- Redis HLL analytika (`activity_hll_optimized.py`)
- Metriky do Google Sheets / Grafana
- REST endpoint `/api/getrating` pro integrace

---

## ✅ TODO

- [ ] Přenést ID log kanálů do `config.py`
- [ ] Fix syntaxe v `activity_hll_optimized.py`
- [ ] Reporty napojit na Redis HLL
- [ ] Přidat `docker-compose.yml` do repo

---

> Dokumentace psaná v češtině, formátována jako pro vývojáře.  
> Vhodné pro sdílení s moderátory i pro deployment tým.
