# Metricord

Discord bot pro správu serveru s pokročilou analytikou a dashboardem.

## Funkce

- **Analytika**: Real-time přehled o aktivitě serveru (DAU/MAU, online stav)
- **Moderace**: Logování událostí, verifikační systém, reporty
- **Dashboard**: Webové rozhraní pro správu a přehledy
- **Automatizace**: Výzvy, notifikace, emoji role

## Struktura

```
📁 bot/           → Discord bot (Cogs, příkazy)
📁 web/           → Webový dashboard (FastAPI + Jinja2)
📁 config/        → Konfigurace
📁 scripts/       → Pomocné skripty
```

## Nasazení

### Požadavky
- Python 3.10+
- Redis
- Discord bot token

### Instalace

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Spuštění

```bash
# Bot
python bot/bot.py

# Dashboard
cd web && uvicorn backend.main:app --port 8092
```

## Konfigurace

Vytvořte `.env` soubor:

```env
DISCORD_TOKEN=your_token
REDIS_HOST=localhost
```

## Licence

Proprietární software. Všechna práva vyhrazena.
