# Nasazení (Debian/Fedora + Docker + Redis)

## Rychlé spuštění (venv)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## systemd služba
`/etc/systemd/system/discord-bot.service`:
```ini
[Unit]
Description=Discord Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/k/repu
Environment="PYTHONUNBUFFERED=1"
ExecStart=/path/k/repu/.venv/bin/python bot.py
Restart=on-failure
User=botuser
Group=botuser

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now discord-bot
journalctl -u discord-bot -f
```

## Docker (image v repo přes `Dockerfile`)
```bash
docker build -t discord-bot .
docker run --name discord-bot   -v $(pwd)/data:/app/data   -e TOKEN="..." \ 
  --restart unless-stopped   discord-bot
```

> Pokud nechceš dávat token v env, nech `bot_token.py` a mountni celý repozitář.

## Redis (HLL analytika)
- Debian/Fedora: nainstaluj a spusť službu (`redis`).
- Docker:
  ```bash
  docker run -d --name redis -p 6379:6379 redis:7
  ```
- V `activity_hll_optimized.py` uprav `CONFIG["REDIS_URL"]` (např. `redis://localhost:6379/0`).