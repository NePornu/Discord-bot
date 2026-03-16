#!/bin/bash

# --- Configuration ---
BOT_DIR="/root/discord-bot"
GO_CORE_DIR="$BOT_DIR/services/core"

# --- Dependency Detection ---
PYTHON_CMD=$(which python3.9 || which python3 || which python)
GO_CMD=$(which go || echo "/usr/local/go/bin/go")

echo "--- NePornu Hybrid Bot System ---"

# --- Cleanup existing instances ---
echo "Cleaning up existing bot processes..."
# Use broader pkill to catch processes started before restructuring
pkill -9 -f "main.py" > /dev/null 2>&1
pkill -9 -f "bot_go" > /dev/null 2>&1
sleep 1 # Wait for processes to exit

echo "Using Python: $PYTHON_CMD"
echo "Using Go:     $GO_CMD"

# Check if Docker is running the bot
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q "^discord-bot-go$"; then
    echo "🔄  Updating discord-bot-go in Docker..."
    docker compose -f "$BOT_DIR/docker-compose.yml" up -d --build discord-bot-go
    echo "✅  Docker container updated."
fi

# Load environment variables
if [ -f "$BOT_DIR/.env" ]; then
    export $(grep -v '^#' "$BOT_DIR/.env" | xargs)
fi

# Override REDIS_URL for local execution (replace docker service name with localhost)
if [[ "$REDIS_URL" == *"@redis:"* ]] || [[ "$REDIS_URL" == *"//redis:"* ]]; then
    export REDIS_URL=$(echo $REDIS_URL | sed 's/@redis:/@localhost:/' | sed 's/\/redis:/\/localhost:/')
    echo "Overriding REDIS_URL to: $REDIS_URL"
fi

# 1. Build Go Core
echo "[1/3] Building Go Core..."
cd "$GO_CORE_DIR" || exit 1
export PATH=$PATH:$(dirname "$GO_CMD")
"$GO_CMD" build -o bot_go main.go
if [ $? -ne 0 ]; then
    echo "❌ Failed to build Go Core!"
    exit 1
fi

# 2. Start Go Core in background
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q "^discord-bot-go$"; then
    echo "⏭️  Skipping host Go Core - already running in Docker."
    GO_PID=""
else
    echo "[2/3] Starting Go Core..."
    ./bot_go > "$BOT_DIR/go_bot.log" 2>&1 &
    GO_PID=$!
    echo "✅ Go Core started with PID $GO_PID (Logs: go_bot.log)"
fi

# Multi-instance protection: Clear stale locks if maintenance script exists
if [ -f "$BOT_DIR/scripts/maintenance/clear_locks.py" ]; then
    echo "🧹 Cleaning stale Redis locks..."
    PYTHONPATH="$BOT_DIR/shared/python" "$PYTHON_CMD" "$BOT_DIR/scripts/maintenance/clear_locks.py" > /dev/null 2>&1
fi

# 3. Start Python Worker in background
echo "[3/3] Starting Python Sidecar (Lite Mode)..."
cd "$BOT_DIR" || exit 1
export BOT_LITE_MODE=1
# Add both root and shared/python to PYTHONPATH
export PYTHONPATH="$BOT_DIR:$BOT_DIR/shared/python:$BOT_DIR/services/worker"
"$PYTHON_CMD" -u services/worker/main.py > "$BOT_DIR/python_worker.log" 2>&1 &
PY_PID=$!
echo "✅ Python Worker started with PID $PY_PID (Logs: python_worker.log)"

echo ""
echo "🚀 Bot is now running in Hybrid Mode!"
if [ -n "$GO_PID" ] && [ -n "$PY_PID" ]; then
    echo "To stop:  kill $GO_PID $PY_PID"
elif [ -n "$PY_PID" ]; then
    echo "To stop:  kill $PY_PID (Go Core is in Docker)"
fi
echo "To logs:  tail -f go_bot.log -f python_worker.log"
