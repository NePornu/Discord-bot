#!/bin/bash

# Configuration
BOT_DIR="/root/discord-bot"
GO_CORE_DIR="$BOT_DIR/go-core"
PYTHON_CMD="/usr/local/bin/python3.9"
GO_CMD="/usr/local/go/bin/go"

echo "Starting NePornu Hybrid Bot System..."

# 1. Build Go Core
echo "Building Go Core..."
cd $GO_CORE_DIR
export PATH=$PATH:/usr/local/go/bin
go build -o bot_go main.go
if [ $? -ne 0 ]; then
    echo "Failed to build Go Core!"
    exit 1
fi

# 2. Start Go Core in background
echo "Starting Go Core..."
./bot_go > $BOT_DIR/go_bot.log 2>&1 &
GO_PID=$!
echo "Go Core started with PID $GO_PID (Logs: go_bot.log)"

# Clear potentially stale locks
echo "Clearing stale Redis locks..."
redis-cli -u redis://localhost:6379/0 del bot:lock:lite bot:lock:primary > /dev/null 2>&1

# 3. Start Python Worker in background
echo "Starting Python Sidecar (Lite Mode)..."
cd $BOT_DIR
export BOT_LITE_MODE=1
export PYTHONPATH=$BOT_DIR
$PYTHON_CMD -u bot/main.py > $BOT_DIR/python_worker.log 2>&1 &
PY_PID=$!
echo "Python Worker started with PID $PY_PID (Logs: python_worker.log)"

echo ""
echo "Bot is now running in Hybrid Mode!"
echo "Use 'kill $GO_PID $PY_PID' to stop everything."
echo "To monitor logs: 'tail -f go_bot.log' or 'tail -f python_worker.log'"
