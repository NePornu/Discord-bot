# Metricord

Metricord je pokročilý distribuovaný Discord bot pro správu serveru s důrazem na analytiku, bezpečnost a moderaci.

## 🚀 Klíčové Funkce

- **Go-Core Výkon**: Hlavní jádro psané v Go pro bleskovou odezvu na příkazy.
- **AI Moderace**: Automatická detekce NSFW avatarů a nevhodného obsahu (Python Worker).
- **Behaviorální Analýza**: Detekce podezřelých vzorců chování a ochrana proti raidům.
- **Komplexní Analytika**: Sledování aktivity (DAU/MAU), online stavů a růstu serveru.
- **Verifikační Systém**: Propracované ověřování uživatelů (OTP, Keycloak integrace).
- **Leveling**: MOTW/Leveling systém s automatickým přidělováním rolí.
- **Dashboard**: Moderní webové rozhraní pro správu všeho na jednom místě.

## 🛠 Architektura

Bot využívá hybridní architekturu spojující výkon Go a flexibilitu Pythonu:
- **Go Core**: Moderace, XP systém, základní příkazy.
- **Python Worker**: ML analýza, pattern detection, analytics syncing.
- **Redis**: Koordinace a sdílení stavu mezi moduly.

Podrobnější informace naleznete v [ARCHITECTURE.md](ARCHITECTURE.md).

## 📦 Instalace a Nasazení

Systém je kompletně kontejnerizován pomocí Dockeru.

### Požadavky
- Docker & Docker Compose
- Discord Bot Token
- Redis (součástí docker-compose)

### Spuštění

1. Zkopírujte `.env.example` do `.env` a vyplňte potřebné údaje:
   ```bash
   cp .env.example .env
   ```
2. Sestavte a spusťte kontejnery:
   ```bash
   docker compose up -d --build
   ```

### Lokální Vývoj

#### Go Core
```bash
cd go-core
go run main.go
```

#### Python Worker
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot/main.py
```

## 📜 Licence

Proprietární software. Všechna práva vyhrazena pro nepornu.cz.
