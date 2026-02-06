#!/bin/bash
set -e

# Calculate root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "[INFO] Restarting all services using Docker Compose..."

# Check if botnet network exists, if not create it (though compose handles it if not external, but we defined it as external)
if ! docker network ls | grep -q botnet; then
    echo "[INFO] Creating external network 'botnet'..."
    docker network create botnet
fi

docker compose down
docker compose up -d --build

echo "[INFO] All services started."
docker compose ps
