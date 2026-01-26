# Instrukce pro nastavení VERIFICATION_LOG_CHANNEL_ID

## Manuální úprava config.py

Otevřete soubor `/root/discord-bot/config.py` a přidejte následující parametr:

```python
# Verification Channels
VERIFICATION_CHANNEL_ID = 1459269521440506110  # Schvalovací zprávy s tlačítky
VERIFICATION_LOG_CHANNEL_ID = 1351911780892409958  # Detailní logy
```

## Restart bota po úpravě

Po úpravě `config.py` je potřeba restartovat Docker container:

```bash
cd /root/discord-bot
docker stop discord-bot
docker rm discord-bot
docker build -t discord-bot .
docker run -d --name discord-bot --network botnet --restart unless-stopped discord-bot
```

## Ověření

Po restartu:
1. Nový uživatel připojený na server vytvoří:
   - **Schvalovací zprávu** s tlačítky v kanálu `1459269521440506110`
   - **Detailní log** v kanálu `1351911780892409958`

2. Zpráva ve schvalovacím kanálu bude obsahovat všechny detaily (avatar, bio, varování)
3. Log kanál bude obsahovat kopii pro archivaci (pokud jsou kanály různé)
