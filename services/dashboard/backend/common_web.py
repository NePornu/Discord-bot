import os
import secrets
from fastapi import Request, HTTPException
from fastapi.templating import Jinja2Templates
from datetime import datetime
from typing import Optional, List, Dict, Any

# Manual .env loading
env_path = "/root/discord-bot/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val.strip('"').strip("'")

# Configuration & Secrets
SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", secrets.token_urlsafe(32))
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", 24))
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1227269599951589508")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "KucYzPIvgrMnbVUW9BI4arnRdwh0OB-n")
DISCORD_REDIRECT_URI_BASE = os.getenv("DISCORD_REDIRECT_URI", "http://207.180.223.191:8092/auth/callback")

admin_ids_raw = os.getenv("ADMIN_USER_IDS", "471218810964410368")
try:
    ADMIN_USER_IDS = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]
except:
    ADMIN_USER_IDS = [471218810964410368]

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Template setup
templates = Jinja2Templates(directory="web/frontend/templates")

# Discord API
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

# Middleware / Helpers
async def require_auth(request: Request):
    allowed_paths = ["/login", "/auth/callback", "/logout"]
    if request.url.path.startswith("/static") or request.url.path in allowed_paths:
        return
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    login_time = request.session.get("login_time")
    if login_time:
        elapsed = (datetime.now() - datetime.fromisoformat(login_time)).total_seconds()
        if elapsed > (SESSION_EXPIRY_HOURS * 3600):
            request.session.clear()
            raise HTTPException(status_code=401, detail="Session expired")

async def require_admin(request: Request):
    await require_auth(request)
    # Check session role
    if request.session.get("role") != "admin":
        # Additional deep check for dynamic admins
        from shared.python.redis_client import get_redis_client
        import json
        user = request.session.get("discord_user")
        if user:
            uid = str(user["id"])
            if int(uid) in ADMIN_USER_IDS:
                return
            r = await get_redis_client()
            is_dynamic = await r.sismember("training:admins", uid)
            if is_dynamic:
                return
        raise HTTPException(status_code=403, detail="Přístup pouze pro administrátory")
