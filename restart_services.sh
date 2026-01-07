
#!/bin/bash
# Stop services
docker stop discord-bot || true
docker rm discord-bot || true
pkill -f "dashboard.main"

echo "Stopped. Waiting 2s..."
sleep 2

# Start Bot via Docker
# Assuming image 'discord-bot' was just built
docker run -d --name discord-bot --network botnet --restart unless-stopped discord-bot
echo "Bot container started."

# Start Dashboard locally
# Using python3 explicitly
nohup python3 -m uvicorn dashboard.main:app --host 0.0.0.0 --port 8092 >> dashboard.log 2>&1 &
echo "Dashboard started."
