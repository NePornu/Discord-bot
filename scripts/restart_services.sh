#!/bin/bash
set -e

# Calculate root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

ACTION=${1:-all}

stop_bot() {
    echo "[INFO] Stopping bot services..."
    for name in "discord-bot" "discord-bot-primary" "discord-bot-dashboard"; do
        if docker ps -a -q --filter "name=$name" | grep -q .; then
            echo "[INFO] Stopping $name container..."
            docker stop $name || true
            docker rm $name || true
        fi
    done
}

start_bot() {
    echo "[INFO] Rebuilding bot image..."
    docker build -t discord-bot-image .
    
    # Extract tokens from config/bot_token.py
    TOKEN_FILE="config/bot_token.py"
    if [ ! -f "$TOKEN_FILE" ]; then
        echo "[ERROR] $TOKEN_FILE not found!"
        exit 1
    fi
    
    PRIMARY_TOKEN=$(grep "^TOKEN =" "$TOKEN_FILE" | cut -d '"' -f 2 | tr -d "'")
    DASH_TOKEN=$(grep "^DASHBOARD_TOKEN =" "$TOKEN_FILE" | cut -d '"' -f 2 | tr -d "'")

    echo "[INFO] Starting PRIMARY bot..."
    docker run -d --name discord-bot-primary --network botnet --restart unless-stopped \
        -e BOT_TOKEN="$PRIMARY_TOKEN" \
        discord-bot-image

    echo "[INFO] Starting DASHBOARD bot (Lite Mode)..."
    docker run -d --name discord-bot-dashboard --network botnet --restart unless-stopped \
        -e BOT_TOKEN="$DASH_TOKEN" \
        -e BOT_LITE_MODE="1" \
        discord-bot-image
}

stop_dash() {
    echo "[INFO] Stopping dashboard..."
    pkill -f "web.backend.main" || true
    for i in {1..5}; do
        if ! pgrep -f "web.backend.main" > /dev/null; then break; fi
        sleep 1
    done
    if pgrep -f "web.backend.main" > /dev/null; then
        pkill -9 -f "web.backend.main" || true
    fi
    # Port cleanup
    PORT_PID=$(lsof -t -i:8092 2>/dev/null) && kill -9 $PORT_PID || true
}

start_dash() {
    echo "[INFO] Starting dashboard..."
    > dashboard.log
    nohup python3 -m uvicorn web.backend.main:app --host 0.0.0.0 --port 8092 >> dashboard.log 2>&1 &
    DASH_PID=$!
    echo "Dashboard PID: $DASH_PID"
    
    echo "[INFO] Waiting for dashboard to become responsive..."
    for i in {1..15}; do
        if curl -s -I http://127.0.0.1:8092/ > /dev/null; then
            echo "✅ Dashboard is UP!"
            return 0
        fi
        sleep 1
    done
    
    # Check if process is still running
    if ! kill -0 $DASH_PID 2>/dev/null; then
         echo "❌ Dashboard process died immediately. Check dashboard.log:"
         tail -n 20 dashboard.log
    else
         echo "❌ Dashboard failed to respond (Process $DASH_PID is running)."
    fi
    exit 1
}

case $ACTION in
    bot)
        stop_bot
        start_bot
        ;;
    dash)
        stop_dash
        start_dash
        ;;
    all)
        stop_bot
        stop_dash
        start_bot
        start_dash
        ;;
    *)
        echo "Usage: $0 {all|bot|dash}"
        exit 1
        ;;
esac
