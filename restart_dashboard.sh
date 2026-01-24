#!/bin/bash
set -e

echo "[INFO] Stopping dashboard..."
# First try SIGTERM
pkill -f "dashboard.main" || true

# Check if it's dead, wait up to 10s
for i in {1..10}; do
    if ! pgrep -f "dashboard.main" > /dev/null; then
        echo "Process stopped."
        break
    fi
    echo "Waiting for process to stop... ($i)"
    sleep 1
done

# Force Kill if still alive
if pgrep -f "dashboard.main" > /dev/null; then
    echo "[WARN] Process stuck, force killing..."
    pkill -9 -f "dashboard.main" || true
    sleep 1
fi

# Ensure Port 8092 is free
if lsof -i :8092 > /dev/null 2>&1; then
    PORT_PID=$(lsof -t -i:8092)
    if [ ! -z "$PORT_PID" ]; then
        echo "[WARN] Killing process $PORT_PID holding port 8092..."
        kill -9 $PORT_PID || true
    fi
fi

echo "[INFO] Starting dashboard..."
if [ -f .env ]; then
    echo "[INFO] Loading environment variables..."
    export $(grep -v '^#' .env | xargs)
fi
> dashboard.log # Clears the log file

nohup python3 -m uvicorn web.backend.main:app --host 0.0.0.0 --port 8092 >> dashboard.log 2>&1 &
DASH_PID=$!
echo "Dashboard PID: $DASH_PID"

# Verify Dashboard Startup
echo "[INFO] Waiting for dashboard to become responsive..."
MAX_RETRIES=20
for i in $(seq 1 $MAX_RETRIES); do
    if curl -s -I http://127.0.0.1:8092/ > /dev/null; then
        echo "✅ Dashboard is UP!"
        exit 0
    fi
    
    if ! kill -0 $DASH_PID 2>/dev/null; then
        echo "❌ Dashboard process died immediately. Check dashboard.log:"
        tail -n 10 dashboard.log
        exit 1
    fi
    
    echo "Waiting... ($i/$MAX_RETRIES)"
    sleep 1
done

echo "❌ Dashboard failed to respond after ${MAX_RETRIES} seconds."
exit 1
