#!/bin/bash

# Local AI Resource Management Script
# Purpose: Toggle between normal operations and AI Training Mode by scaling down Fluxer services.

FLUXER_DIR="/root/fluxer"
BOT_DIR="/root/discord-bot"

case "$1" in
    "start")
        echo "Starting AI Training Mode..."
        echo "Scaling down Fluxer services to free up RAM..."
        cd "$FLUXER_DIR" && docker compose stop api gateway worker marketing admin media meilisearch clickhouse cassandra livekit minio
        echo "Keeping core services: Postgres (used by Discourse), Redis (Fluxer), and Caddy (Proxy)."
        echo "Server resources freed. Local LLM (Ollama) can now run with full capacity."
        ;;
    "stop")
        echo "Stopping AI Training Mode..."
        echo "Restoring Fluxer services..."
        cd "$FLUXER_DIR" && docker compose start
        echo "Normal operations restored."
        ;;
    "status")
        echo "Current system status:"
        docker stats --no-stream
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        echo "  start   - Scale down Fluxer services for AI training."
        echo "  stop    - Scale up Fluxer services for normal operation."
        echo "  status  - Show current resource usage."
        exit 1
        ;;
esac
