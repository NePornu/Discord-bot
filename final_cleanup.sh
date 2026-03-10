#!/bin/bash
set -e

REPO_DIR="/root/discord-bot"
cd "$REPO_DIR"

echo "--- GIT HISTORY SCRUB & RESTRUCTURING FIX ---"

# 1. Kill duplicate bot processes 
echo "[1/4] Terminating existing bot processes..."
pkill -9 -f "python.*services/worker/main.py" || true
pkill -9 -f "python.*services/dashboard/backend/dashboard.py" || true
pkill -9 -f "python.*services/dashboard/backend/main.py" || true
echo "Processes cleared."

# 2. Scrub History (The Big Reset)
echo "[2/4] Collapsing history to scrub forbidden secrets..."
# We go back to origin/main but keep all your literal file changes unstaged.
git reset --soft origin/main

# 3. Clean up the state
echo "[3/4] Ensuring sensitive files are physically removed..."
[ -f "shared/python/config/bot_token.py" ] && rm "shared/python/config/bot_token.py" && echo "Removed: bot_token.py"
[ -d "data/ollama" ] && rm -rf data/ollama && echo "Removed: data/ollama"
[ -d "ollama" ] && rm -rf ollama && echo "Removed: ollama"

# Ensure secrets are not in the index
git rm --cached shared/python/config/bot_token.py 2>/dev/null || true
git add .gitignore
git add .

# 4. Final Clean Commit
echo "[4/4] Creating a clean restructure commit..."
git commit -m "chore: Full project restructuring and security hardening"

echo ""
echo "✅ History scrubbed and project ready!"
echo "🚀 YOU CAN NOW RUN: git push"
echo "♻️ AND RESTART: bash run.sh"
