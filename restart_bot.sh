#!/bin/bash
set -e

echo "[INFO] Stopping bot..."
# First try SIGTERM
pkill -f "bot.main" || true

# Check if it's dead, wait up to 10s
for i in {1..10}; do
    if ! pgrep -f "bot.main" > /dev/null; then
        echo "Process stopped."
        break
    fi
    echo "Waiting for process to stop... ($i)"
    sleep 1
done

# Force Kill if still alive
if pgrep -f "bot.main" > /dev/null; then
    echo "[WARN] Process stuck, force killing..."
    pkill -9 -f "bot.main" || true
    sleep 1
fi

echo "[INFO] Starting bot..."
> bot.log # Clears the log file

# Set Lite Mode to 0 (Full Mode) or 1 as needed - assuming full mode for correct stats
export BOT_LITE_MODE=0 
nohup python3 -m bot.main >> bot.log 2>&1 &
BOT_PID=$!
echo "Bot PID: $BOT_PID"

echo "[INFO] Bot started in background. Check bot.log for details."
