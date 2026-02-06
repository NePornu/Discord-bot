#!/bin/bash

# Kill existing processes
echo "[INFO] Killing stuck processes..."
pkill -9 -f "bot.main" || echo "No bot process found"
pkill -9 -f "web.backend.main" || echo "No backend process found"

# Start Redis if not running
echo "[INFO] Checking Redis..."
service redis-server start || echo "Redis start failed or already running"

# Wait a moment
sleep 2

# Start Bot
echo "[INFO] Starting Bot..."
nohup ./Python-3.9.18/python -u -m bot.main > bot_std.log 2>&1 &
BOT_PID=$!
echo "Bot PID: $BOT_PID"

# Start Dashboard
echo "[INFO] Starting Dashboard..."
nohup ./Python-3.9.18/python -m uvicorn web.backend.main:app --host 0.0.0.0 --port 8092 > dashboard_std.log 2>&1 &
DASH_PID=$!
echo "Dashboard PID: $DASH_PID"

# Wait and check
sleep 5

if ps -p $BOT_PID > /dev/null; then
  echo "✅ Bot is running"
else
  echo "❌ Bot failed to start. Check bot_std.log"
fi

if ps -p $DASH_PID > /dev/null; then
  echo "✅ Dashboard is running"
else
  echo "❌ Dashboard failed to start. Check dashboard_std.log"
fi
