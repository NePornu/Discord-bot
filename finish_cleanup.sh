#!/bin/bash
set -e

echo "--- FINAL CLEANUP & VERIFICATION ---"

# 1. Consolidate shared python files
echo "[1/4] Consolidating shared Python files..."
cd /root/discord-bot/shared
mv __init__.py keycloak_client.py keys.py pattern_logic.py redis_client.py python/ 2>/dev/null || true
cd /root/discord-bot

# 2. Organize data and ollama
echo "[2/4] Organizing data..."
mkdir -p data/ollama
[ -d "ollama" ] && mv ollama/* data/ollama/ 2>/dev/null && rmdir ollama || echo "ollama already moved or missing"

# 3. Final cleanup of temporary scripts
echo "[3/4] Cleaning up temporary scripts..."
rm -f restructure.sh
rm -f scripts/cleanup_old_keys.sh
rm -f test_access.txt

# 4. Restart everything
echo "[4/4] Restarting services..."
bash run.sh

echo "✅ Project restructuring is fully complete!"
