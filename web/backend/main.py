from fastapi import FastAPI, Request, Form, Cookie, Response, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
from pathlib import Path
import redis.asyncio as redis
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict
import secrets
import httpx
import sys
sys.path.append('/root/discord-bot')
from shared.redis_client import get_redis_client
try:
    from config.dashboard_secrets import (
        SECRET_KEY, ACCESS_TOKEN, SESSION_EXPIRY_HOURS,
        DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
        ADMIN_USER_IDS, BOT_TOKEN
    )
except ImportError:
    SECRET_KEY = secrets.token_urlsafe(32)
    ACCESS_TOKEN = secrets.token_urlsafe(32)
    SESSION_EXPIRY_HOURS = 24
    DISCORD_CLIENT_ID = ""
    DISCORD_CLIENT_SECRET = ""
    DISCORD_REDIRECT_URI = "http://localhost:8092/auth/callback"
    ADMIN_USER_IDS = []
    BOT_TOKEN = ""
    print(f"WARNING: Using generated secrets.")

# import GUILD_ID from config REMOVED - using dynamic session
# from config import GUILD_ID (Deleted)

from .utils import (
    load_member_stats, 
    get_activity_stats, 
    get_deep_stats_redis,
    get_challenge_config, 
    save_challenge_config,
    get_realtime_online_count,
    get_summary_card_data,
    get_redis_dashboard_stats,
    save_user_guilds,
    get_user_guilds,
    get_bot_guilds,
    get_trend_analysis, get_engagement_score, get_insights, get_security_score,
    get_voice_leaderboard, get_command_stats, get_traffic_stats, get_channel_distribution,
    get_time_comparisons, get_leaderboard_data,
    get_dashboard_team, add_dashboard_user, remove_dashboard_user, get_dashboard_permissions,
    get_daily_stats, get_action_weights
)

# ... (rest of imports)

app = FastAPI(title="Bot Dashboard", docs_url=None, redoc_url=None)

# Add session middleware for authentication (same_site=lax for OAuth redirects)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_EXPIRY_HOURS * 3600, same_site="lax", https_only=False)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/img/hero_dashboard.png") # Placeholder


@app.get("/select-server", response_class=HTMLResponse)
async def select_server_page(request: Request):
    """Page to select which server to manage."""
    user = request.session.get("discord_user")
    if not user:
        return RedirectResponse(url="/")
        
    # Get user's managed guilds from Redis
    user_guilds = await get_user_guilds(user["id"])
    
    # If cache is missing (None), force re-login to fetch guilds
    if user_guilds is None:
        return RedirectResponse(url="/login")
        
    bot_guilds = await get_bot_guilds()
    
    # Mark which ones have the bot
    for g in user_guilds:
        g["bot_in_guild"] = str(g["id"]) in bot_guilds
        
    return templates.TemplateResponse("select_server.html", {
        "request": request, 
        "guilds": user_guilds,
        "user": user
    })

@app.get("/select-server/{guild_id}")
async def set_active_server(request: Request, guild_id: str):
    """Set the active guild in session and redirect to dashboard."""
    user = request.session.get("discord_user")
    if not user:
        return RedirectResponse(url="/")

    # Verify user has access to this guild
    user_guilds = await get_user_guilds(user["id"])
    if not any(g["id"] == guild_id for g in user_guilds):
        raise HTTPException(status_code=403, detail="Access denied to this server")
        
    # Check if bot is in guild (optional, but good for UX)
    bot_guilds = await get_bot_guilds()
    if guild_id not in bot_guilds:
        # Redirect to invite URL if bot is not there?
        # For now, just warn or allow (maybe they want to add it)
        pass

    # Find guild name and icon
    guild_name = "Unknown Server"
    guild_icon = None
    for g in user_guilds:
        if g["id"] == guild_id:
            guild_name = g["name"]
            guild_icon = g.get("icon")
            break

    request.session["guild_id"] = guild_id
    request.session["guild_name"] = guild_name
    request.session["guild_icon"] = guild_icon
    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, start_date: str = None, end_date: str = None, role_id: str = None):
    try:
        return await _dashboard_logic(request, start_date, end_date, role_id)
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        try:
            with open("/root/discord-bot/dashboard_crash.log", "w") as f:
                f.write(err_msg)
        except: pass
        
        if hasattr(e, "status_code"): raise e
        return HTMLResponse(content=f"""
        <html><body style="background:#111;color:#f88;font-family:monospace;padding:20px;">
        <h2>Internal Server Error Debugger</h2>
        <div style="white-space:pre-wrap;">{err_msg}</div>
        </body></html>
        """, status_code=500)

@app.get("/features", response_class=HTMLResponse)
async def landing_features(request: Request):
    return templates.TemplateResponse("landing_features.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
async def landing_about(request: Request):
    # Fetch real aggregate stats for About page
    stats = {"servers": "1", "users": "---", "uptime": "99.9%"}
    try:
        r = await get_redis_client()
        bot_guilds = await r.smembers("bot:guilds")
        
        total_msgs = 0
        total_users = 0
        
        for gid in bot_guilds:
            tm = await r.get(f"stats:total_msgs:{gid}") or "0"
            tu = await r.get(f"presence:total:{gid}") or "0"
            
            total_msgs += int(tm)
            total_users += int(tu)
            
        stats["servers"] = len(bot_guilds)
        stats["users"] = f"{total_users:,}".replace(",", " ")
        stats["messages"] = f"{total_msgs:,}".replace(",", " ")
        
    except Exception as e:
        print(f"Error fetching about stats: {e}")
        
    context = {"request": request, "stats": stats}
    return templates.TemplateResponse("landing_about.html", context)

@app.get("/privacy", response_class=HTMLResponse)
async def legal_privacy(request: Request):
    return templates.TemplateResponse("docs/privacy.html", {"request": request})

@app.get("/terms", response_class=HTMLResponse)
async def legal_terms(request: Request):
    return templates.TemplateResponse("docs/terms.html", {"request": request})

@app.get("/changelog", response_class=HTMLResponse)
async def docs_changelog(request: Request):
    return templates.TemplateResponse("docs/changelog.html", {"request": request})

@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request):
    return templates.TemplateResponse("docs/support.html", {"request": request})

async def _dashboard_logic(request: Request, start_date: str = None, end_date: str = None, role_id: str = None):
    """Main Dashboard Overview."""
    # Check if user is authenticated
    user = request.session.get("discord_user")
    
    # If not authenticated -> Landing Page
    if not user:
        # Landing page logic with stats...
        # note: for landing page stats, we might need a DEFAULT guild or Global stats?
        # For now, let's just show stats for the "Flagship" server if configured, or sum of all?
        # Let's try to get stats for the first bot guild found.
        try:
             r = await get_redis_client()
             bot_guilds = await r.smembers("bot:guilds")
             
             # Aggregate or pick one? Let's aggregate for "Community Analytics" feel
             total_msgs = 0
             total_users = 0
             max_days = 0
             
             for gid in bot_guilds:
                 tm = await r.get(f"stats:total_msgs:{gid}") or "0"
                 tu = await r.get(f"presence:total:{gid}") or "0"
                 hourly = await r.keys(f"stats:hourly:{gid}:*")
                 
                 total_msgs += int(tm)
                 total_users += int(tu)
                 max_days = max(max_days, len(hourly))
             
             pass
             
             public_stats = {
                 "messages": f"{total_msgs:,}".replace(",", " "),
                 "users": f"{total_users:,}".replace(",", " "),
                 "days": max_days
             }
        except Exception as e:
            print(f"Error fetching dashboard guilds: {e}")
            public_stats = {"messages": "---", "users": "---", "days": "0"}
             
        return templates.TemplateResponse("landing.html", {"request": request, "stats": public_stats})

    # User IS authenticated
    # Check for Active Guild in Session
    guild_id = request.session.get("guild_id")
    if not guild_id:
        return RedirectResponse(url="/select-server")
    
    # Filter Persistence & Defaults
    start_date = start_date or request.session.get("start_date", "2025-12-21")
    end_date = end_date or request.session.get("end_date", "2026-01-20")
    role_id = role_id or request.session.get("role_id", "all")
    
    # Save to session
    request.session["start_date"] = start_date
    request.session["end_date"] = end_date
    request.session["role_id"] = role_id

    guild_id = int(guild_id)
    
    # --- PERMISSION CHECK ---
    # Check if user has dashboard access
    from .utils import get_dashboard_permissions
    perms = await get_dashboard_permissions(guild_id, user["id"])
    
    # If NO permissions, show ONLY XP Leaderboard (Restricted View)
    if not perms:
        try:
             # Fetch XP Leaderboard Data manually for this view
             r = await get_redis_client()
             xp_key = f"levels:xp:{guild_id}"
             top_users = await r.zrevrange(xp_key, 0, 49, withscores=True) # Top 50
             
             leaderboard_data = []
             for i, (uid_str, xp_score) in enumerate(top_users, 1):
                 uid = str(uid_str)
                 xp = int(float(xp_score))
                 
                 # Resolve User Info
                 u_info = await r.hgetall(f"user:info:{uid}") or {}
                 username = u_info.get("name") or u_info.get("username") or f"User {uid}"
                 avatar = u_info.get("avatar")
                 
                 # Calculate Level (Replicating formula from levels.py)
                 # We need config for accurate calculation
                 xp_conf = await r.hgetall("config:xp_formula")
                 a = int(xp_conf.get("a", 50))
                 b = int(xp_conf.get("b", 200)) 
                 c_const = int(xp_conf.get("c", 100))
                 
                 import math
                 def calc_level(cxp):
                     if cxp < c_const: return 0
                     c_val = c_const - cxp
                     d = (b**2) - (4*a*c_val)
                     if d < 0: return 0
                     return int((-b + math.sqrt(d)) / (2*a))
                 
                 def xp_for_lvl(lvl):
                     return a * (lvl ** 2) + b * lvl + c_const
                     
                 level = calc_level(xp)
                 next_xp = xp_for_lvl(level + 1)
                 prev_xp = xp_for_lvl(level) if level > 0 else 0
                 
                 needed = next_xp - prev_xp
                 current = xp - prev_xp
                 progress = int((current / needed) * 100) if needed > 0 else 0
                 
                 leaderboard_data.append({
                     "rank": i,
                     "username": username,
                     "user_id": uid,
                     "avatar": avatar,
                     "level": level,
                     "xp": xp,
                     "progress": min(100, max(0, progress))
                 })
                 
             return templates.TemplateResponse("leaderboard.html", {
                 "request": request, 
                 "leaderboard": leaderboard_data, 
                 "user": user,
                 "is_restricted": True
             })
             
        except Exception as e:
            print(f"Restricted view error: {e}")
            return templates.TemplateResponse("leaderboard.html", {"request": request, "leaderboard": [], "user": user, "error": str(e)})

    # --- END PERMISSION CHECK ---
    
    # Fetch roles for the filter
    from .utils import get_cached_roles
    roles = await get_cached_roles(guild_id)
    roles_list = [(r["id"], r["name"]) for r in roles]


    



    # 1. Member Growth & Flow
    member_stats = await load_member_stats(guild_id, start_date=start_date, end_date=end_date)
    
    # 2. Activity
    activity_stats = await get_activity_stats(guild_id, start_date=start_date, end_date=end_date)
    
    # 3. Deep Stats
    deep_stats = await get_deep_stats_redis(guild_id=guild_id, start_date=start_date, end_date=end_date)
    
    # 3b. Redis Dashboard Stats
    redis_stats = await get_redis_dashboard_stats(guild_id, start_date=start_date, end_date=end_date, role_id=role_id)
    deep_stats.update(redis_stats)
    
    # 4. Realtime Snapshot
    realtime_active = await get_realtime_online_count(guild_id)



    # 5. Global Data Check
    summary = await get_summary_card_data(guild_id=guild_id)
    has_any_data = summary["discord"]["msgs"] > 0

    # KPIs & Extract current values for Summary Card
    total_leaves = sum(member_stats["leaves"]) if member_stats.get("leaves") else 0
    current_total = member_stats["total"][-1] if member_stats.get("total") else 0
    current_dau = activity_stats["dau_data"][-1] if activity_stats.get("dau_data") else 0
    current_mau = activity_stats["mau_data"][-1] if activity_stats.get("mau_data") else 0
    current_wau = deep_stats.get("wau_data", [])[-1] if deep_stats.get("wau_data") else 0
    
    # Summary Card Data (ONLY real stats - no placeholders)
    summary_stats = await get_summary_card_data(
        discord_dau=current_dau,
        discord_mau=current_mau,
        discord_wau=current_wau,
        discord_users=current_total, 
        guild_id=guild_id
    )
    
    # Calculate churn using REAL total members
    real_total_members = summary_stats["discord"]["users"]
    churn_rate = round((total_leaves / max(1, real_total_members)) * 100, 2)
    
    # Define Context for Template
    context = {
        "request": request,
        "stats": summary_stats,
        "member_stats": member_stats,
        "activity_stats": activity_stats,
        "deep_stats": deep_stats,
        "redis_stats": redis_stats,
        "realtime_active": realtime_active,
        "churn_rate": churn_rate,
        "active_staff_count": 0, # Placeholder or calc
        "roles": roles_list,
        "user_role": role_id,
        "start_date": start_date,
        "end_date": end_date,
        "guild_id": guild_id,
        "user": user,
        
        # KPI Metrics
        "total_members": summary_stats["discord"]["users"],
        "avg_dau": activity_stats.get("avg_dau", 0),
        "avg_msg_len": deep_stats.get("avg_msg_len", "-"),
        "peak_day": deep_stats.get("peak_day", "-"),
        "reply_ratio": deep_stats.get("reply_ratio", 0),
        
        # Flattened Stats for ChartJS
        "dau_labels": activity_stats.get("dau_labels", []),
        "dau_data": activity_stats.get("dau_data", []),
        "labels": member_stats.get("labels", []),
        "joins_data": member_stats.get("joins", []),
        "leaves_data": member_stats.get("leaves", []),
        "total_data": member_stats.get("total", []),
        
        # Chart Variables
        "hourly_labels": redis_stats.get("hourly_labels", []),
        "hourly_activity": redis_stats.get("hourly_activity", []),
        "retention_labels": deep_stats.get("retention_labels", []),
        "dau_mau_ratio": deep_stats.get("dau_mau_ratio", []),
        "dau_wau_ratio": deep_stats.get("dau_wau_ratio", []),
        "msglen_labels": redis_stats.get("msglen_labels", []),
        "msglen_data": redis_stats.get("msglen_data", []),
        "weekly_labels": deep_stats.get("weekly_labels", []),
        "weekly_data": deep_stats.get("weekly_data", [])
    }

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    context.update(sidebar_ctx)
    
    return templates.TemplateResponse("index.html", context)



# Authentication dependency (runs AFTER middleware)
async def require_auth(request: Request):
    """Check if user is authenticated."""
    # Allow login/auth routes without redirect
    allowed_paths = ["/login", "/auth/callback", "/logout", "/request-otp", "/verify-otp", "/resend-otp"]
    if request.url.path.startswith("/static") or request.url.path in allowed_paths:
        return
    
    # Check authentication
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Check session expiry
    login_time = request.session.get("login_time")
    if login_time:
        elapsed = (datetime.now() - datetime.fromisoformat(login_time)).total_seconds()
        if elapsed > (SESSION_EXPIRY_HOURS * 3600):
            request.session.clear()
            raise HTTPException(status_code=401, detail="Session expired")

async def require_admin(request: Request):
    """Check if user is admin (for protected routes)."""
    await require_auth(request)
    if request.session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Přístup pouze pro administrátory")

async def get_sidebar_context(request: Request) -> Dict[str, Any]:
    """
    Globally inject sidebar data via Flat Variable Resolution.
    Resolves active guild data server-side and maps to flat template variables.
    """
    user = request.session.get("discord_user")
    guild_id = request.session.get("guild_id")
    
    # DEBUG: Diagnostic print
    print(f"[Sidebar Debug] Session ID: {guild_id}")
    
    # Fallback: Query Param (Self-Healing)
    if not guild_id:
        q_guild_id = request.query_params.get("guild_id")
        if q_guild_id:
            print(f"[Sidebar Debug] Recovered ID from Query: {q_guild_id}")
            guild_id = q_guild_id
            # Auto-heal session
            if user:
                request.session["guild_id"] = guild_id
    
    # Internal resolution container
    resolved_guild = None
    
    if user and guild_id:
        # STRATEGY 1: Optimistic Session Check
        s_name = request.session.get("guild_name")
        s_icon = request.session.get("guild_icon")
        
        if s_name and s_name not in ["Neznámý server", "Žádný server"]:
            resolved_guild = {"name": s_name, "icon": s_icon}
        
        # Deep Resolution
        if not resolved_guild:
            try:
                # STRATEGY 2: User's Cached Guilds
                from .utils import get_user_guilds
                user_guilds = await get_user_guilds(user["id"])
                
                match = None
                if user_guilds:
                    match = next((g for g in user_guilds if str(g["id"]) == str(guild_id)), None)
                
                # STRATEGY 3: Redis Guild Info
                if not match:
                    r = await get_redis_client()
                    info = await r.hgetall(f"guild:info:{guild_id}")
                    if info and "name" in info:
                        match = {"name": info["name"], "icon": info.get("icon")}
                
                # STRATEGY 4: Discord API
                if not match:
                     async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            f"https://discord.com/api/v10/guilds/{guild_id}",
                            headers={"Authorization": f"Bot {BOT_TOKEN}"}
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            match = {"name": data["name"], "icon": data.get("icon")}
                            # Cache it
                            r = await get_redis_client()
                            await r.hset(f"guild:info:{guild_id}", mapping={"name": data["name"], "icon": data.get("icon") or ""})
                            
                if match:
                    resolved_guild = match
                    # Persist back to session
                    request.session["guild_name"] = resolved_guild["name"]
                    request.session["guild_icon"] = resolved_guild.get("icon")

            except Exception as e:
                print(f"Sidebar Resolution Error: {e}")

    # Fallbacks for Flat Variables
    # Explicitly return None if no guild found, to trigger "Select Server" UI state
    # BUT if we have a guild_id in session, we MUST show the Active State, even if name is missing.
    final_name = resolved_guild["name"] if resolved_guild else None
    
    if not final_name and guild_id:
        final_name = "Načítání..." # Force Active State for valid ID
        
    final_icon = resolved_guild["icon"] if resolved_guild else None
    
    # If we have an ID but no name, ensure we display something generic or try to use session ID?
    # Actually "Žádný server" is fine if resolution completely failed.

    return {
        "sidebar_guild_id": guild_id,
        "sidebar_guild_name": final_name,
        "sidebar_guild_icon": final_icon,
        # Remove object/list injections
    }

# Nastavení cest
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "frontend" / "static"
TEMPLATES_DIR = BASE_DIR.parent / "frontend" / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Discord OAuth2 routes
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

@app.get("/docs", response_class=HTMLResponse)
@app.get("/docs/{page_name}", response_class=HTMLResponse)
async def docs_page(request: Request, page_name: str = "index"):
    """Serve documentation pages with safety check."""
    allowed_pages = {
        "index", "setup", "commands", "security", "analytics", "export",
        "faq", "support", "ai", "backfill", "roles", "insights",
        "privacy", "terms", "changelog"
    }
    
    if page_name not in allowed_pages:
        # Fallback to index or 404
        return RedirectResponse(url="/docs")
        
    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    
    context = {"request": request, "page_name": page_name}
    context.update(sidebar_ctx)
    return templates.TemplateResponse(f"docs/{page_name}.html", context)

@app.get("/login")
async def login_page(request: Request):
    """Redirect to Discord OAuth."""
    if not DISCORD_CLIENT_ID or DISCORD_CLIENT_ID == "YOUR_CLIENT_ID_HERE":
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Discord OAuth not configured. Contact administrator."
        })
    
    # Build OAuth URL
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds"
    }
    auth_url = f"{DISCORD_AUTH_URL}?" + "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=auth_url)

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, error: str = None):
    """Handle Discord OAuth callback with HTML redirect for cookie persistence."""
    if error:
        return templates.TemplateResponse("login.html", {"request": request, "error": f"Discord error: {error}"})
    
    if not code:
        return RedirectResponse(url="/login")
    
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_resp = await client.post(DISCORD_TOKEN_URL, data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI
            })
            
            if token_resp.status_code != 200:
                print(f"Token error: {token_resp.text}")
                return templates.TemplateResponse("login.html", {"request": request, "error": "Failed to authenticate with Discord"})
            
            token_data = token_resp.json()
            access_token = token_data["access_token"]
            
            # Fetch user info
            headers = {"Authorization": f"Bearer {access_token}"}
            user_resp = await client.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)
            user_data = user_resp.json()
            
            # Fetch user guilds
            guilds_resp = await client.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers)
            guilds_data = guilds_resp.json() if guilds_resp.status_code == 200 else []
        
        # Determine role
        user_id = int(user_data["id"])
        is_admin = user_id in ADMIN_USER_IDS
        
        # Determine guilds where user has Admin or Manage Guild permissions
        # 0x8 = Administrator, 0x20 = Manage Guild
        # Determine guilds where user has Admin or Manage Guild permissions
        # 0x8 = Administrator, 0x20 = Manage Guild
        managed_guilds = []
        for g in guilds_data:
            perms = int(g.get("permissions", 0))
            is_admin_perm = bool(perms & 0x8)
            is_manage_guild = bool(perms & 0x20)
            is_owner = g.get("owner", False)
            


            if is_admin_perm or is_manage_guild or is_owner:
                managed_guilds.append({
                    "id": g["id"], 
                    "name": g["name"], 
                    "icon": g.get("icon"),
                    "is_admin": is_admin_perm or is_owner, # Owner is implicitly superuser
                    "is_mod_candidate": is_manage_guild # 0x20 is just a candidate
                })
        
        # --- RBAC CHECK ---
        # Include guilds where user is a Dashboard User (even if not Discord Admin)
        # Let's check known bot guilds for membership
        r = await get_redis_client()
        bot_guild_ids = await r.smembers("bot:guilds")
        
        for bg_id in bot_guild_ids:
            # Check if user is in this guild's team
            if await r.sismember(f"dashboard:team:{bg_id}", str(user_id)):
                # Fetch guild info (we might not have it from user's guild list if we didn't fetch full list or if scopes limited)
                # But we have it from guilds_data if they are in the server
                g_info = next((g for g in guilds_data if g["id"] == bg_id), None)
                if g_info:
                     # Check if we already added it (e.g. they are also admin)
                     existing = next((x for x in managed_guilds if x["id"] == bg_id), None)
                     if existing:
                         existing["is_team_member"] = True
                     else:
                         managed_guilds.append({
                            "id": g_info["id"],
                            "name": g_info["name"],
                            "icon": g_info.get("icon"),
                            "is_team_member": True,
                            "is_admin": False
                         })

        # Remove duplicates
        seen = set()
        unique_managed = []
        for g in managed_guilds:
            if g["id"] not in seen:
                unique_managed.append(g)
                seen.add(g["id"])
        
        managed_guilds = unique_managed
        is_mod = len(managed_guilds) > 0

        # Store in session - MINIMAL DATA ONLY to prevent cookie overflow
        request.session["authenticated"] = True
        request.session["login_time"] = datetime.now().isoformat()
        
        # Only store essential user info
        request.session["discord_user"] = {
            "id": user_data["id"],
            "username": user_data.get("global_name") or user_data["username"],
            "avatar": user_data.get("avatar")
        }
        
        # Store managed guilds in Redis instead of whole list
        from .utils import save_user_guilds
        await save_user_guilds(user_data["id"], managed_guilds)
        
        if is_admin:
            request.session["role"] = "admin"
        elif is_mod:
            request.session["role"] = "mod"
        else:
            request.session["role"] = "guest"
        
        # Save session intentionally: status_code=303 ensures Set-Cookie is processed before redirect
        
        # Return HTML with meta refresh to ensure cookie is set
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta http-equiv="refresh" content="1;url=/" />
            <title>Redirecting...</title>
            <style>
                body { background: #0a0a0f; color: white; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                .loader { border: 4px solid #333; border-top: 4px solid #5865F2; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; }
                @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                .container { text-align: center; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="loader" style="margin: 0 auto 20px;"></div>
                <h2>Přihlášení úspěšné!</h2>
                <p>Přesměrování na dashboard...</p>
                <script>setTimeout(function(){ window.location.href = "/"; }, 1000);</script>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        print(f"OAuth error: {e}")
        return templates.TemplateResponse("login.html", {"request": request, "error": "Authentication failed. Try again."})

@app.get("/debug/session")
async def debug_session(request: Request):
    """Debug session content."""
    return {
        "session_keys": list(request.session.keys()),
        "auth": request.session.get("authenticated"),
        "role": request.session.get("role"),
        "user_id": request.session.get("discord_user", {}).get("id")
    }

@app.get("/logout")
async def logout(request: Request):
    """Logout and clear session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)

# Exception handler for 401 (redirect to login)
@app.exception_handler(401)
async def redirect_to_login_handler(request: Request, exc: HTTPException):
    return RedirectResponse(url="/", status_code=302)


# --- TEAM MANAGEMENT API ---

import pydantic

class TeamUser(pydantic.BaseModel):
    user_id: str
    username: str
    avatar: Optional[str] = None
    permissions: List[str]

@app.get("/api/settings/team")
async def get_team_api(request: Request):
    """Get list of team members."""
    await require_auth(request)
    guild_id = request.session.get("guild_id")
    if not guild_id: raise HTTPException(400, "No guild selected")
    
    # Check if user can manage team
    # Either Admin/Mod OR has 'manage_team' permission
    user_id = request.session.get("discord_user", {}).get("id")
    role = request.session.get("role")
    
    perms = await get_dashboard_permissions(guild_id, user_id, role)
    if "*" not in perms and "manage_team" not in perms:
        raise HTTPException(403, "Insufficient permissions")
        
    team = await get_dashboard_team(guild_id)
    return team

@app.post("/api/settings/team")
async def add_team_member(request: Request, member: TeamUser):
    """Add or update a team member."""
    await require_auth(request)
    guild_id = request.session.get("guild_id")
    
    user_id = request.session.get("discord_user", {}).get("id")
    role = request.session.get("role")
    
    perms = await get_dashboard_permissions(guild_id, user_id, role)
    if "*" not in perms and "manage_team" not in perms:
        raise HTTPException(403, "Insufficient permissions")
        
    success = await add_dashboard_user(
        guild_id, 
        member.user_id, 
        {"username": member.username, "avatar": member.avatar or ""},
        member.permissions
    )
    
    if success: return {"status": "ok"}
    else: raise HTTPException(500, "Failed to save user")

@app.delete("/api/settings/team/{target_id}")
async def remove_team_member(request: Request, target_id: str):
    """Remove a team member."""
    await require_auth(request)
    guild_id = request.session.get("guild_id")
    
    user_id = request.session.get("discord_user", {}).get("id")
    role = request.session.get("role")
    
    perms = await get_dashboard_permissions(guild_id, user_id, role)
    if "*" not in perms and "manage_team" not in perms:
        raise HTTPException(403, "Insufficient permissions")
        
    success = await remove_dashboard_user(guild_id, target_id)
    return {"status": "ok" if success else "error"}


@app.get("/settings/team", response_class=HTMLResponse)
async def team_settings_page(request: Request):
    """Team Management Page."""
    await require_auth(request)
    guild_id = request.session.get("guild_id")
    if not guild_id: return RedirectResponse("/select-server")
    
    # Check access
    user_id = request.session.get("discord_user", {}).get("id")
    role = request.session.get("role")
    perms = await get_dashboard_permissions(guild_id, user_id, role)
    
    if "*" not in perms and "manage_team" not in perms:
        sidebar_ctx = await get_sidebar_context(request)
        ctx = {
            "request": request,
            "message": "Nemáte oprávnění spravovat tým."
        }
        ctx.update(sidebar_ctx)
        return templates.TemplateResponse("activity_restricted.html", ctx)

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    
    ctx = {
        "request": request,
        "user": request.session.get("discord_user"),
        "current_perms": perms,
        "permissions_list": [
            {"id": "view_stats", "name": "Zobrazit Statistiky", "desc": "Read-only přístup k dashboardu"},
            {"id": "manage_settings", "name": "Spravovat Nastavení", "desc": "Úprava vah a nastavení bota"},
            {"id": "export_data", "name": "Export Dat", "desc": "Stahování CSV/JSON exportů"},
            {"id": "manage_team", "name": "Spravovat Tým", "desc": "Přidávání a odebírání uživatelů"}
        ]
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("team.html", ctx)

# --- XP API ---
@app.get("/api/leaderboard/xp")
async def get_xp_leaderboard(request: Request):
    """Get XP Leaderboard."""
    # Public access allowed? Or require auth? 
    # Usually leaderboards are public or at least guild-auth specific.
    # Let's require auth for now.
    await require_auth(request)
    guild_id = request.session.get("guild_id")
    if not guild_id: raise HTTPException(400, "No guild selected")
    
    r = await get_redis_client()
    key = f"levels:xp:{guild_id}"
    
    # Get Top 100
    top_users = await r.zrevrange(key, 0, 99, withscores=True)
    
    # Enrich with user info
    data = []
    
    # We might need to batch fetch user info or use cached
    current_rank = 1
    for i, (uid, xp) in enumerate(top_users, 1):
        user_info = await r.hgetall(f"user:info:{uid}") or {}
        username = user_info.get("username", "Unknown")
        
        # Skip deleted users
        if username == "Deleted User":
            continue
            
        # Calculate level 
        # (Duplicate logic from bot, maybe move to shared utils?)
        # Simple recalc here:
        xp = int(xp)
        level = 0
        if xp >= 100:
             # Quadratic approximation inverse
             # xp = 5x^2 + 50x + 100
             # 5x^2 + 50x + (100-xp) = 0
             import math
             a, b, c = 5, 50, 100 - xp
             d = (b**2) - (4*a*c)
             if d >= 0:
                 level = int((-b + math.sqrt(d)) / (2*a))
        
        data.append({
            "rank": current_rank,
            "user_id": uid,
            "username": username,
            "avatar": user_info.get("avatar"),
            "xp": xp,
            "level": level
        })
        current_rank += 1
        
    return data



# Challenge config routes moved - /settings is now for action weights

@app.get("/commands", response_class=HTMLResponse)
async def commands_page(request: Request, _=Depends(require_auth)):
    sidebar_ctx = await get_sidebar_context(request)
    ctx = {"request": request}
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("docs/commands.html", ctx)

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, start_date: str = None, end_date: str = None, role_id: str = None, _=Depends(require_auth)):
    """New advanced analytics page with channel stats and leaderboards."""
    user = request.session.get("discord_user", {})
    guild_id = request.session.get("guild_id")
    if not guild_id:
        return RedirectResponse(url="/select-server")
    guild_id = int(guild_id)

    # Filter Persistence & Defaults
    from datetime import datetime, timedelta
    
    # 1. Load Defaults from Settings
    def_range = request.session.get("default_date_range", "last_30_days")
    def_role = request.session.get("default_role_id", "all")
    
    # Load layout order (migrating old 'dashboard_order' to 'analytics_order' if needed)
    widget_order = request.session.get("analytics_order") or request.session.get("dashboard_order", [])
    
    # 2. Handle Date Logic
    # If URL params are missing, apply Default Range (reset view).
    # If URL params are present, use them.
    if start_date is None or end_date is None:
        now = datetime.now()
        if def_range == "last_7_days":
            start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        elif def_range == "last_30_days":
            start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        elif def_range == "this_month":
            start_date = now.replace(day=1).strftime("%Y-%m-%d")
        elif def_range == "all_time":
            start_date = "2023-01-01"
        else:
             # Fallback
             start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        
        end_date = now.strftime("%Y-%m-%d")
    
    # 3. Handle Role Logic
    if role_id is None:
        role_id = def_role

    # Save to session (updating persistence)
    request.session["start_date"] = start_date
    request.session["end_date"] = end_date
    request.session["role_id"] = role_id
    
    # Dashboard Order
    DEFAULT_ORDER = [
        "wow_card", "mom_card", 
        "top_channels", "leaderboard", 
        "peak_analysis", 
        "channel_dist", "commands", "voice_stats", "traffic",
        "trend_analysis", "engagement", 
        "export", "insights"
    ]
    widget_order = request.session.get("dashboard_order", DEFAULT_ORDER)

    # Real data check for backfill warning
    summary = await get_summary_card_data(guild_id=guild_id)
    has_any_data = summary["discord"]["msgs"] > 0

    # Fetch roles for the filter
    from .utils import get_cached_roles
    roles = await get_cached_roles(guild_id)
    roles_list = [(r["id"], r["name"]) for r in roles]

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    ctx = {
        "request": request,
        "user": user,
        "start_date": start_date,
        "end_date": end_date,
        "selected_role": role_id,
        "roles": roles_list,
        "has_any_data": has_any_data,
        "widget_order": widget_order,
        "all_widgets": [
            ('wow_card', '📈 Trends (WoW)'),
            ('mom_card', '📊 Trends (MoM)'),
            ('top_channels', '🏆 Top Channels'),
            ('leaderboard', '👑 Leaderboard'),
            ('peak_analysis', '🔥 Peak Time'),
            ('channel_dist', '📢 Channel Dist'),
            ('commands', '🤖 Commands'),
            ('voice_stats', '🎙️ Voice Stats'),
            ('traffic', '🚦 Traffic'),
            ('trend_analysis', '📈 Growth Trend'),
            ('engagement', '🎯 Engagement'),
            ('export', '📤 Export Tools'),
            ('insights', '💡 Insights'),
            ('growth_chart', '📈 Member Growth'),
            ('hourly_chart', '⏰ Hourly Activity'),
            ('weekday_chart', '📅 Weekday Activity'),
            ('msg_len_chart', '📏 Msg Lengths'),
            ('weekend_chart', '🎉 Weekend Ratio'),
            ('xp_leaderboard', '🏆 XP Leaderboard')
        ]
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("analytics.html", ctx)



@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, _=Depends(require_auth)):
    """User profile page with managed servers list."""
    user = request.session.get("discord_user", {})
    user_id = user.get("id")
    
    # Get user's managed guilds
    from .utils import get_user_guilds, get_bot_guilds
    managed_guilds = await get_user_guilds(user_id)
    bot_guild_ids = set(await get_bot_guilds())
    
    # MANUAL OVERRIDE: Since bot process cannot run on Python 3.7 to sync guilds,
    # we manually mark known active guilds here so the dashboard works.
    bot_guild_ids.add("615171377783242769") # NePornu
    
    # Prepare server list with status
    servers = []
    for g in managed_guilds:
        is_active = str(g["id"]) in bot_guild_ids
        servers.append({
            "id": g["id"],
            "name": g["name"],
            "icon": g.get("icon"),
            "active": is_active,
            "dashboard_url": f"/activity?guild_id={g['id']}" if is_active else None,
            "invite_url": f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&permissions=8&scope=bot" if not is_active else None
        })

    # SELF-HEAL for PROFILE PAGE
    current_guild_id = request.session.get("guild_id")
    current_guild_icon = request.session.get("guild_icon")
    
    if current_guild_id:
        # Try to find match
        matched_g = next((g for g in managed_guilds if str(g["id"]) == str(current_guild_id)), None)
        if not matched_g and request.session.get("guild_name"):
             matched_g = next((g for g in managed_guilds if g["name"] == request.session.get("guild_name")), None)
        
        if matched_g:
            current_guild_icon = matched_g.get("icon")
            # Update session if needed
            if request.session.get("guild_icon") != current_guild_icon:
                request.session["guild_icon"] = current_guild_icon

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    ctx = {
        "request": request,
        "user": user,
        "role": request.session.get("role"),
        "servers": servers
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("profile.html", ctx)

@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request, guild_id: str = None, start_date: str = None, end_date: str = None, role_id: str = None, _=Depends(require_auth)):
    """Moderator Activity Page with manual Redis aggregation."""
    
    # Check permission
    user_role = request.session.get("role", "guest")
    user_id = request.session.get("discord_user", {}).get("id")
    
    # Defaults
    if not guild_id:
        guild_id = request.session.get("guild_id")
    
    target_guild_id = guild_id or "615171377783242769" # Default to NePornu if all else fails

    # Filter Persistence
    if start_date:
        request.session["start_date"] = start_date
    else:
        start_date = request.session.get("start_date", "2025-12-21")
        
    if end_date:
        request.session["end_date"] = end_date
    else:
        end_date = request.session.get("end_date", "2026-01-20")
    
    # If not admin, check if user manages this guild
    if user_role != "admin":
        if user_role == "mod":
            from .utils import get_user_guilds
            user_guilds = await get_user_guilds(user_id)
            managed_ids = [g["id"] for g in user_guilds]
            
            # Check managed
            if target_guild_id not in managed_ids:
                 return templates.TemplateResponse("activity_restricted.html", {
                    "request": request,
                    "message": "Nemáte práva moderátora pro zobrazení statistik této guildy."
                })
            # Inject Global Sidebar Context
            sidebar_ctx = await get_sidebar_context(request)
            
            # Guest
            ctx = {
                "request": request,
                "message": "Přístup k této stránce je omezen. Nemáte moderátorská práva."
            }
            ctx.update(sidebar_ctx)
            return templates.TemplateResponse("activity_restricted.html", ctx)
    
    # Fetch Stats
    # Fetch Stats
    from .utils import get_activity_stats, get_redis_dashboard_stats, get_deep_stats_redis
    
    # 1. Redis Based stats
    activity_stats = await get_activity_stats(int(target_guild_id), start_date=start_date, end_date=end_date)
    
    # Get deep stats (consistency, leaderboard, etc.) - Uses Redis HLL
    deep_stats = await get_deep_stats_redis(int(target_guild_id), start_date=start_date, end_date=end_date, role_id=role_id)
    
    # 2. Redis Based stats (Hourly, Heatmap, Msg Len)
    redis_stats = await get_redis_dashboard_stats(int(target_guild_id), start_date=start_date, end_date=end_date)
    
    # Parse Dates
    from datetime import datetime as dt, timedelta
    import json
    
    if start_date:
        try: d_start = dt.strptime(start_date, "%Y-%m-%d")
        except: d_start = dt.now() - timedelta(days=30)
    else:
        d_start = dt.now() - timedelta(days=30)
        
    if end_date:
        try: d_end = dt.strptime(end_date, "%Y-%m-%d")
        except: d_end = dt.now()
    else:
        d_end = dt.now()
        
    # User requested NO LIMIT "ať vypisuje vše"
    # We use batching below to handle large ranges safely.
    warning_msg = None

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    
    # Fetch roles for the filter
    from .utils import get_cached_roles
    roles = await get_cached_roles(int(target_guild_id))
    roles_list = [(r["id"], r["name"]) for r in roles]

    ctx = {
        "request": request,
        "guild_id": target_guild_id,
        "activity": activity_stats,
        "deep_stats": deep_stats,
        "redis_stats": redis_stats,
        "warning_msg": warning_msg,
        "user_role": user_role,
        "user": request.session.get("discord_user"),
        
        # Mapping for activity.html charts
        "daily_labels": deep_stats.get("daily_labels", []),
        "daily_hours": deep_stats.get("daily_weighted_hours", []), 
        "leaderboard": deep_stats.get("leaderboard", []),
        "total_hours_30d": deep_stats.get("total_hours_30d", 0),
        "active_staff_count": deep_stats.get("active_staff_count", 0),
        "top_action": deep_stats.get("top_action", "-"),
        "roles": roles_list,
        "selected_role": role_id or "all",
        "start_date": start_date or d_start.strftime("%Y-%m-%d"),
        "end_date": end_date or d_end.strftime("%Y-%m-%d"),
        "warning": warning_msg
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("activity.html", ctx)

@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(request: Request, _=Depends(require_auth)):
    """Render XP Leaderboard page."""
    user = request.session.get("discord_user", {})
    guild_id = request.session.get("guild_id")
    if not guild_id:
        return RedirectResponse(url="/select-server")
    guild_id = int(guild_id)
    
    # 1. Fetch XP Data (ALL USERS)
    r = await get_redis_client()
    key = f"levels:xp:{guild_id}"
    # Fetch ALL users (-1)
    top_users = await r.zrevrange(key, 0, -1, withscores=True)
    
    leaderboard_data = []
    
    # 2. Process Data
    # Fetch XP Formula Config
    xp_conf = await r.hgetall("config:xp_formula")
    CA = int(xp_conf.get("a", 50))
    CB = int(xp_conf.get("b", 200))
    CC = int(xp_conf.get("c", 100))

    import math
    current_rank = 1
    for i, (uid, xp) in enumerate(top_users, 1):
        user_info = await r.hgetall(f"user:info:{uid}") or {}
        xp = int(xp)
        
        # Level Calc (Configurable)
        # XP = A*L^2 + B*L + C => A*L^2 + B*L + (C - XP) = 0
        level = 0
        if xp >= CC:
             a, b, c = CA, CB, CC - xp
             d = (b**2) - (4*a*c)
             if d >= 0:
                 level = int((-b + math.sqrt(d)) / (2*a))
        
        # Calculate progress to next level
        current_level_xp = CA * (level**2) + CB * level + CC
        next_level_xp = CA * ((level+1)**2) + CB * (level+1) + CC
        
        # XP needed for NEXT level relative to current level base
        xp_needed = next_level_xp - current_level_xp
        xp_progress = xp - current_level_xp
        
        # Clamp for safety
        if xp_needed <= 0: xp_needed = 1
        progress_pct = min(100, max(0, int((xp_progress / xp_needed) * 100)))

        # Resolve Display Name
        display_name = user_info.get("username") or user_info.get("name")
        
        # Skip unknown or deleted users
        if not display_name or display_name == "Deleted User":
             continue
        
        leaderboard_data.append({
            "rank": current_rank,
            "user_id": uid,
            "username": display_name,
            "avatar": user_info.get("avatar"),
            "xp": xp,
            "level": level,
            "progress": progress_pct,
            "next_level_xp": int(next_level_xp)
        })
        current_rank += 1

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    
    ctx = {
        "request": request,
        "user": user,
        "leaderboard": leaderboard_data
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("leaderboard.html", ctx)

    
    
    # End of routes




@app.get("/activity/user/{uid}", response_class=HTMLResponse)
async def user_activity_page(request: Request, uid: int, start_date: str = None, end_date: str = None, _=Depends(require_auth)):
    """Detailed activity page for a specific user."""
    
    # Defaults to 30 days for the chart
    today = datetime.now().date()
    try:
        if start_date:
            d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        else:
            d_start = today - timedelta(days=30)
            
        if end_date:
            d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            d_end = today
    except ValueError:
        d_start = today - timedelta(days=30)
        d_end = today

    user_info = {"name": f"User {uid}", "avatar": "", "roles": []}
    daily_stats = {} # YYYY-MM-DD -> weighted seconds
    
    stats_summary = defaultdict(float) # metric -> count/seconds
    
    try:
        r = await get_redis_client()
        gid = 615171377783242769
        
        # 1. Get User Info
        info = await r.hgetall(f"user:info:{uid}")
        if info:
            user_info["name"] = info.get("name", f"User {uid}")
            user_info["avatar"] = info.get("avatar", "")
            if "roles" in info and info["roles"]:
                # Fetch role names
                role_ids = info["roles"].split(",")
                all_roles = await r.hgetall(f"guild:roles:{gid}")
                user_info["roles"] = [all_roles.get(rid, f"Role {rid}") for rid in role_ids if rid in all_roles]

        # 2. Get Activity Data for User (iterate through days)
        weights = await get_action_weights(r)
        
        current_day = d_start
        while current_day <= d_end:
            day_str = current_day.strftime("%Y-%m-%d")
            
            daily_data = await get_daily_stats(r, gid, uid, current_day)
            
            if daily_data:
                # Aggregate to summary
                for metric, val in daily_data.items():
                    if metric != "_version":
                        stats_summary[metric] += val
                
                # Calculate weighted time for daily chart
                chat_t = daily_data.get("chat_time", 0)
                voice_t = daily_data.get("voice_time", 0)
                
                action_t = 0
                for action_metric in ["bans", "kicks", "timeouts", "unbans", "verifications", "msg_deleted", "role_updates"]:
                    action_t += daily_data.get(action_metric, 0) * weights.get(action_metric, 0)
                
                weighted_total = chat_t + voice_t + action_t
                
                if day_str not in daily_stats: daily_stats[day_str] = 0
                daily_stats[day_str] += weighted_total
            
            current_day += timedelta(days=1)

        pass
    except Exception as e:
        print(f"Error fetching user activity: {e}")

    # Format Chart
    sorted_days = sorted(daily_stats.keys())
    daily_labels = [d[5:] for d in sorted_days]
    daily_values = [round(daily_stats[d] / 3600, 1) for d in sorted_days]
    
    # Calculate Totals
    chat_h = round(stats_summary["chat_time"] / 3600, 1)
    voice_h = round(stats_summary["voice_time"] / 3600, 1)
    
    total_weighted = 0
    for m, val in stats_summary.items():
        w = weights.get(m, 1)
        if m == "messages": w = 0
        total_weighted += (val * w)
        
    total_h = round(total_weighted / 3600, 1)
    
    action_breakdown = {
        "Bans": int(stats_summary["bans"]),
        "Kicks": int(stats_summary["kicks"]),
        "Timeouts": int(stats_summary["timeouts"]),
        "Unbans": int(stats_summary["unbans"]),
        "Verifications": int(stats_summary["verifications"]),
        "Deleted Msgs": int(stats_summary["msg_deleted"]),
        "Role Updates": int(stats_summary["role_updates"])
    }
    
    total_actions = sum(action_breakdown.values())

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    
    ctx = {
        "request": request,
        "user_info": user_info,
        "days": sorted_days,
        "values": daily_values,
        "is_bot": user_info.get("bot", False),
        "summary": {
            "total_h": total_h,
            "chat_h": chat_h,
            "voice_h": voice_h,
            "actions": total_actions,
            "breakdown": action_breakdown
        }
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("user_activity.html", ctx)

# Helper functions moved to utils.py

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, _=Depends(require_admin)):
    """Settings page for configuring weights (admin only)."""
    # Defaults
    weights = {
        "bans": 300, "kicks": 180, "timeouts": 180, "unbans": 120, 
        "verifications": 120, "msg_deleted": 60, "role_updates": 30,
        "chat_time": 1, "voice_time": 1,
        "session_base": 180, "char_weight": 1, "reply_weight": 60, "msg_weight": 0
    }
    
    # Security score defaults
    security_weights = {"mod_ratio": 25, "security": 25, "engagement": 25, "moderation": 25}
    security_ideals = {
        "mod_ratio_min": 50, "mod_ratio_max": 100,
        "dau_percent": 10, "mod_actions_min": 1, "mod_actions_max": 5,
        "verification_level": 2
    }
    
    # XP Formula Defaults
    xp_formula = {"a": 50, "b": 200, "c": 100}
    
    try:
        r = await get_redis_client()
        weights = await get_action_weights(r)
        
        # Load security score settings
        stored_sec_weights = await r.hgetall("config:security_weights")
        if stored_sec_weights:
            for k, v in stored_sec_weights.items():
                security_weights[k] = int(v)
        
        stored_sec_ideals = await r.hgetall("config:security_ideals")
        if stored_sec_ideals:
            for k, v in stored_sec_ideals.items():
                security_ideals[k] = float(v) if '.' in str(v) else int(v)

        # Load XP Formula
        stored_xp = await r.hgetall("config:xp_formula")
        if stored_xp:
            xp_formula["a"] = int(stored_xp.get("a", 50))
            xp_formula["b"] = int(stored_xp.get("b", 200))
            xp_formula["c"] = int(stored_xp.get("c", 100))
            xp_formula["min"] = int(stored_xp.get("min", 15))
            xp_formula["max"] = int(stored_xp.get("max", 25))
            xp_formula["voice_min"] = int(stored_xp.get("voice_min", 5))
            xp_formula["voice_max"] = int(stored_xp.get("voice_max", 10))
            
    except Exception as e:
        print(f"Error loading settings: {e}")
        # Keep defaults on error
        
    # Fetch roles for default role selector
    roles_list = []
    guild_id = request.session.get("guild_id")
    if guild_id:
        from .utils import get_cached_roles
        roles = await get_cached_roles(int(guild_id))
        roles_list = [(r["id"], r["name"]) for r in roles]

    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)

    ctx = {
        "request": request, 
        "weights": weights,
        "show_deleted_data": request.session.get("show_deleted_data", False),
        "default_date_range": request.session.get("default_date_range", "last_30_days"),
        "default_role_id": request.session.get("default_role_id", "all"),
        "roles": roles_list,
        "security_weights": security_weights,
        "security_ideals": security_ideals,
        "xp_formula": xp_formula
    }
    ctx.update(sidebar_ctx)
    return templates.TemplateResponse("settings.html", ctx)

@app.post("/settings/general")
async def update_general_settings(
    request: Request, 
    show_deleted: Optional[str] = Form(None), 
    default_date_range: str = Form("last_30_days"),
    default_role_id: str = Form("all"),
    _=Depends(require_auth)
):
    """Update general settings in session."""
    # Checkbox sends "on" if checked, None if unchecked
    request.session["show_deleted_data"] = (show_deleted == "on")
    request.session["default_date_range"] = default_date_range
    request.session["default_role_id"] = default_role_id
    return RedirectResponse(url="/settings", status_code=303)

@app.post("/settings/dashboard")
async def update_dashboard_layout(
    request: Request,
    show_comparisons: Optional[str] = Form(None),
    show_top_channels: Optional[str] = Form(None),
    show_leaderboard: Optional[str] = Form(None),
    show_peak_analysis: Optional[str] = Form(None),
    show_channel_dist: Optional[str] = Form(None),
    show_commands: Optional[str] = Form(None),
    show_voice: Optional[str] = Form(None),
    show_traffic: Optional[str] = Form(None),
    show_tools: Optional[str] = Form(None),
    widget_order: Optional[str] = Form(None),
    widget_spans: Optional[str] = Form(None),
    page: str = Form("analytics"),
    _=Depends(require_auth)
):
    """Update dashboard layout preferences in session."""
    if page == "analytics":
        layout = {
            "show_comparisons": show_comparisons == "on",
            "show_top_channels": show_top_channels == "on",
            "show_leaderboard": show_leaderboard == "on",
            "show_peak_analysis": show_peak_analysis == "on",
            "show_channel_dist": show_channel_dist == "on",
            "show_commands": show_commands == "on",
            "show_voice": show_voice == "on",
            "show_traffic": show_traffic == "on",
            "show_tools": show_tools == "on"
        }
        request.session["dashboard_layout"] = layout
    
    # Save widget spans
    if widget_spans:
        import json
        try:
            spans_dict = json.loads(widget_spans)
            current_spans = request.session.get("dashboard_spans", {})
            current_spans.update(spans_dict)
            request.session["dashboard_spans"] = current_spans
        except Exception as e:
            print(f"Invalid widget spans JSON: {e}")
    
    # Save order if provided
    if widget_order:
        import json
        try:
            order_list = json.loads(widget_order)
            if page == "overview":
                request.session["overview_order"] = order_list
            elif page == "predictions":
                request.session["predictions_order"] = order_list
            else:
                request.session["analytics_order"] = order_list
                request.session["dashboard_order"] = order_list # legacy backup
        except:
            print("Invalid widget order JSON")

    # Redirect back to the correct page
    redirect_url = "/analytics"
    if page == "overview": redirect_url = "/"
    elif page == "predictions": redirect_url = "/predictions"
    
    return RedirectResponse(url=redirect_url, status_code=303)

@app.post("/settings/security-score")
async def update_security_score_settings(
    request: Request,
    weight_mod_ratio: int = Form(25),
    weight_security: int = Form(25),
    weight_engagement: int = Form(25),
    weight_moderation: int = Form(25),
    ideal_mod_ratio_min: int = Form(50),
    ideal_mod_ratio_max: int = Form(100),
    ideal_dau_percent: int = Form(10),
    ideal_mod_actions_min: float = Form(1),
    ideal_mod_actions_max: float = Form(5),
    ideal_verification_level: int = Form(2),
    _=Depends(require_admin)
):
    """Update security score weights and ideals in Redis."""
    try:
        r = await get_redis_client()
        
        # Save weights
        await r.hset("config:security_weights", mapping={
            "mod_ratio": weight_mod_ratio,
            "security": weight_security,
            "engagement": weight_engagement,
            "moderation": weight_moderation
        })
        
        # Save ideals
        await r.hset("config:security_ideals", mapping={
            "mod_ratio_min": ideal_mod_ratio_min,
            "mod_ratio_max": ideal_mod_ratio_max,
            "dau_percent": ideal_dau_percent,
            "mod_actions_min": ideal_mod_actions_min,
            "mod_actions_max": ideal_mod_actions_max,
            "verification_level": ideal_verification_level
        })
        
    except Exception as e:
        print(f"Error saving security score settings: {e}")
        
    return RedirectResponse(url="/settings", status_code=303)

@app.get("/predictions")
async def predictions_page(request: Request, _=Depends(require_auth)):
    # Inject Global Sidebar Context
    sidebar_ctx = await get_sidebar_context(request)
    context = {
        "request": request,
        "widget_order": request.session.get("predictions_order", [])
    }
    context.update(sidebar_ctx)
    return templates.TemplateResponse("predictions.html", context)

@app.get("/api/predictions-data")
async def get_predictions_data(request: Request, _=Depends(require_auth)):
    guild_id = request.session.get("guild_id")
    if not guild_id: return JSONResponse({"status": "error"}, status_code=400)
    
    from .utils import load_member_stats, get_redis, get_activity_stats
    import datetime
    
    end_dt = datetime.datetime.now()
    r = await get_redis()
    
    # ============================================
    # ČÁST 1: PREDIKCE ČLENŮ (REALISTICKÁ)
    # ============================================
    
    # A) Získej SKUTEČNÝ aktuální počet členů
    current_members_str = await r.get(f"presence:total:{guild_id}")
    if not current_members_str:
        current_members_str = await r.get(f"stats:total_members:{guild_id}")
    current_members = int(current_members_str) if current_members_str else 0
    
    # B) Načti historická data (měsíční přírůstky)
    stats = await load_member_stats(guild_id)  # Bez filtrů = celá historie
    joins_history = stats.get('joins', [])
    leaves_history = stats.get('leaves', [])
    dates = stats.get('labels', [])
    
    # C) Spočítej průměrný MĚSÍČNÍ růst za posledních 12 měsíců
    recent_months = 12
    recent_joins = joins_history[-recent_months:] if len(joins_history) >= recent_months else joins_history
    recent_leaves = leaves_history[-recent_months:] if len(leaves_history) >= recent_months else leaves_history
    
    if recent_joins:
        avg_monthly_joins = sum(recent_joins) / len(recent_joins)
        avg_monthly_leaves = sum(recent_leaves) / len(recent_leaves) if recent_leaves else 0
        avg_monthly_growth = avg_monthly_joins - avg_monthly_leaves
    else:
        avg_monthly_growth = 0
        avg_monthly_joins = 0
        avg_monthly_leaves = 0
    
    # D) Predikce na 30 dní = přibližně 1 měsíc
    predicted_growth_30d = round(avg_monthly_growth)
    predicted_members_30d = current_members + predicted_growth_30d
    
    # E) Procentuální změna
    growth_pct = round((predicted_growth_30d / current_members * 100), 2) if current_members > 0 else 0
    
    # F) Vytvoř forecast pro graf (měsíční rozlišení, zobraz 6 měsíců dopředu)
    forecast_dates = []
    forecast_members = []
    
    running_total = current_members
    for i in range(1, 7):  # 6 měsíců dopředu
        future_date = end_dt + datetime.timedelta(days=30*i)
        forecast_dates.append(future_date.strftime("%Y-%m"))
        running_total += round(avg_monthly_growth)
        forecast_members.append(running_total)
    
    # G) Historie pro graf (posledních 12 měsíců)
    history_dates = dates[-12:] if len(dates) > 12 else dates
    history_members = stats.get('total', [])[-12:] if len(stats.get('total', [])) > 12 else stats.get('total', [])
    
    # Pokud nemáme historii, použij aktuální počet
    if not history_members:
        history_members = [current_members]
        history_dates = [end_dt.strftime("%Y-%m")]
    
    # 3. Advanced Activity Forecast (Trend + Seasonality)
    # Step A: Fetch daily activity time-series for last 30 days
    from .utils import get_redis
    r = await get_redis()
    
    activity_history = []
    hist_dates = []
    
    # 30 days back
    for i in range(30):
        d = end_dt - datetime.timedelta(days=29-i)
        d_str = d.strftime("%Y%m%d")
        # Sum hourly stats for this day
        h_data = await r.hgetall(f"stats:hourly:{guild_id}:{d_str}")
        daily_sum = sum(int(float(v)) for v in h_data.values())
        activity_history.append(daily_sum)
        hist_dates.append(d)
        
    # Step B: Calculate Trend (Linear Regression on Activity)
    # y = mx + c
    act_x = list(range(len(activity_history)))
    act_y = activity_history
    n_act = len(act_y)
    
    if n_act > 1:
        s_x = sum(act_x)
        s_y = sum(act_y)
        s_xy = sum(i*j for i, j in zip(act_x, act_y))
        s_xx = sum(i*i for i in act_x)
        try:
            act_slope = (n_act*s_xy - s_x*s_y) / (n_act*s_xx - s_x**2)
            act_intercept = (s_y - act_slope*s_x) / n_act
        except:
            act_slope = 0
            act_intercept = sum(act_y)/n_act
    else:
        act_slope = 0
        act_intercept = 0

    # Step C: Calculate Seasonality (Weekday Baselines)
    # We want to know: "How much does a Monday deviate from the average day?"
    weekday_totals = [0] * 7
    weekday_counts = [0] * 7
    
    for i, val in enumerate(activity_history):
        wd = hist_dates[i].weekday()
        weekday_totals[wd] += val
        weekday_counts[wd] += 1
        
    global_avg = sum(activity_history) / n_act if n_act > 0 else 1
    if global_avg == 0: global_avg = 1
    
    seasonality_indices = []
    for d in range(7):
        avg_for_day = weekday_totals[d] / weekday_counts[d] if weekday_counts[d] > 0 else global_avg
        # Index > 1 means busier than average, < 1 means quieter
        seasonality_indices.append(avg_for_day / global_avg)
        
    # Step D: Project Future
    today_weekday = end_dt.weekday()
    forecast_activity = []
    forecast_day_labels = []
    cz_days = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
    
    for i in range(1, 8):
        # Forecast day index (0-indexed relative to history end)
        future_x = (n_act - 1) + i
        
        # 1. Base Trend Level
        trend_level = act_slope * future_x + act_intercept
        if trend_level < 0: trend_level = 0
        
        # 2. Apply Seasonality
        future_wd = (today_weekday + i) % 7
        seasonal_adjust = seasonality_indices[future_wd]
        
        final_pred = trend_level * seasonal_adjust
        
        forecast_activity.append(round(final_pred))
        forecast_day_labels.append(cz_days[future_wd])
        
    expected_msgs_tomorrow = forecast_activity[0]
    
    # 4. DAU Prediction with Trend + Seasonality
    act = await get_activity_stats(guild_id, days=30)
    daus = act.get('dau_data', [])
    dau_labels = act.get('dau_labels', [])
    avg_dau = act.get('avg_dau', 0)
    
    # DAU Trend calculation
    dau_n = len(daus)
    if dau_n > 1:
        dau_x = list(range(dau_n))
        dau_sum_x = sum(dau_x)
        dau_sum_y = sum(daus)
        dau_sum_xy = sum(i*j for i, j in zip(dau_x, daus))
        dau_sum_xx = sum(i*i for i in dau_x)
        try:
            dau_slope = (dau_n*dau_sum_xy - dau_sum_x*dau_sum_y) / (dau_n*dau_sum_xx - dau_sum_x**2)
            dau_intercept = (dau_sum_y - dau_slope*dau_sum_x) / dau_n
        except:
            dau_slope = 0
            dau_intercept = avg_dau
    else:
        dau_slope = 0
        dau_intercept = avg_dau
    
    # DAU Seasonality (weekday patterns)
    dau_weekday_totals = [0] * 7
    dau_weekday_counts = [0] * 7
    for i, val in enumerate(daus):
        if i < len(hist_dates):
            wd = hist_dates[i].weekday()
            dau_weekday_totals[wd] += val
            dau_weekday_counts[wd] += 1
    
    dau_global_avg = sum(daus) / dau_n if dau_n > 0 else 1
    if dau_global_avg == 0: dau_global_avg = 1
    
    dau_seasonality = []
    for d in range(7):
        avg_for_day = dau_weekday_totals[d] / dau_weekday_counts[d] if dau_weekday_counts[d] > 0 else dau_global_avg
        dau_seasonality.append(avg_for_day / dau_global_avg)
    
    # DAU Forecast (7 days)
    dau_forecast = []
    dau_forecast_labels = []
    for i in range(1, 8):
        future_x = (dau_n - 1) + i
        trend_level = dau_slope * future_x + dau_intercept
        if trend_level < 0: trend_level = 0
        
        future_wd = (today_weekday + i) % 7
        seasonal_adjust = dau_seasonality[future_wd] if future_wd < len(dau_seasonality) else 1
        
        final_dau = round(trend_level * seasonal_adjust)
        dau_forecast.append(final_dau)
        
        future_date = end_dt + datetime.timedelta(days=i)
        dau_forecast_labels.append(future_date.strftime("%Y-%m-%d"))
    
    expected_dau = dau_forecast[0] if dau_forecast else round(avg_dau)
    
    # MAU calculation (unique users in last 30 days)
    mau_key = f"hll:mau:{guild_id}:{end_dt.strftime('%Y%m')}"
    mau = await r.pfcount(mau_key)
    if mau == 0:
        # Fallback: estimate MAU from DAU
        mau = round(avg_dau * 3.5) if avg_dau > 0 else 0
    
    # DAU/MAU Ratio (Stickiness)
    dau_mau_ratio = round((avg_dau / mau * 100), 1) if mau > 0 else 0
    
    # MAU Forecast (simple: current + monthly growth rate)
    mau_growth_rate = 1.02  # Assume 2% monthly growth as baseline
    mau_forecast = [mau]
    for i in range(1, 4):  # 3 months ahead
        mau_forecast.append(round(mau_forecast[-1] * mau_growth_rate))
    
    # 5. Churn Risk - založeno na posledních 3 měsících odchodů
    recent_leaves_3m = leaves_history[-3:] if len(leaves_history) >= 3 else leaves_history
    total_recent_leaves = sum(recent_leaves_3m) if recent_leaves_3m else 0
    churn_rate = (total_recent_leaves / current_members) if current_members > 0 else 0
    churn_score = min(round(churn_rate * 100 * 10), 100)
    if total_recent_leaves == 0: churn_score = 0
    
    # Build Response Dict
    res_dict = {
        "history": {
            "dates": history_dates,
            "members": history_members,
            "joins": joins_history[-12:] if len(joins_history) > 12 else joins_history,
            "leaves": leaves_history[-12:] if len(leaves_history) > 12 else leaves_history
        },
        "forecast": {
            "dates": forecast_dates,
            "members": forecast_members,
            "days": forecast_day_labels,
            "activity": forecast_activity
        },
        "dau": {
            "history": daus,
            "history_labels": dau_labels,
            "forecast": dau_forecast,
            "forecast_labels": dau_forecast_labels,
            "avg": round(avg_dau),
            "trend": "up" if dau_slope > 0 else "down" if dau_slope < 0 else "stable"
        },
        "mau": {
            "current": mau,
            "forecast": mau_forecast,
            "dau_mau_ratio": dau_mau_ratio
        },
        "predictions": {
            "members_30d": predicted_members_30d,
            "members_growth_pct": growth_pct,
            "expected_msgs_tomorrow": expected_msgs_tomorrow,
            "expected_dau": expected_dau,
            "avg_dau": round(avg_dau),
            "churn_risk": churn_score,
            "avg_monthly_growth": round(avg_monthly_growth, 1),
            "current_members": current_members
        },
        "channels": []
    }
    
    try:
        from .utils import get_channel_distribution
        # Get distribution for last 30 days as baseline (Long-term data)
        dist = await get_channel_distribution(int(guild_id), days=30)
        # Fetch names (defined at bottom of this file)
        channels_info = await get_discord_channels(int(guild_id))
        cmap = {str(c['id']): c['name'] for c in channels_info}
        
        predicted_channels = []
        total_baseline = sum(c['count'] for c in dist) if dist else 1
        
        for d in dist[:5]: # Top 5
            share = d['count'] / total_baseline
            pred_count = round(share * expected_msgs_tomorrow)
            predicted_channels.append({
                "name": cmap.get(str(d['channel_id']), f"#{d['channel_id']}"),
                "count": pred_count
            })
        
        res_dict["channels"] = predicted_channels
        return JSONResponse(res_dict)
        
    except Exception as e:
        print(f"Error in channel predictions: {e}")
        return JSONResponse(res_dict)

@app.post("/settings/weights")
async def update_weights(
    request: Request,
    bans: int = Form(...), kicks: int = Form(...), timeouts: int = Form(...),
    unbans: int = Form(...), verifications: int = Form(...), 
    msg_deleted: int = Form(...), role_updates: int = Form(...),
    chat_time: int = Form(...), voice_time: int = Form(...),
    session_base: int = Form(180), char_weight: int = Form(1),
    reply_weight: int = Form(60), msg_weight: int = Form(0),
    _=Depends(require_auth)
):
    """Update action weights in Redis."""
    try:
        r = await get_redis_client()
        
        mapping = {
            "bans": bans, "kicks": kicks, "timeouts": timeouts,
            "unbans": unbans, "verifications": verifications,
            "msg_deleted": msg_deleted, "role_updates": role_updates,
            "chat_time": chat_time, "voice_time": voice_time,
            "session_base": session_base, "char_weight": char_weight,
            "reply_weight": reply_weight, "msg_weight": msg_weight
        }
        
        await r.hset("config:action_weights", mapping=mapping)
        
        # INVALIDATE ALL CACHED STATS
        await r.incr("config:weights_version")
        
        pass
        
    except Exception as e:
        print(f"Error saving weights: {e}")
        
    return RedirectResponse(url="/settings", status_code=303)

@app.post("/settings/xp-formula")
async def update_xp_formula(
    request: Request,
    xp_a: int = Form(...),
    xp_b: int = Form(...),
    xp_c: int = Form(...),
    xp_min: int = Form(15),
    xp_max: int = Form(25),
    xp_voice_min: int = Form(5),
    xp_voice_max: int = Form(10),
    _=Depends(require_admin)
):
    """Update XP formula coefficients in Redis."""
    try:
        r = await get_redis_client()
        await r.hset("config:xp_formula", mapping={
            "a": xp_a,
            "b": xp_b,
            "c": xp_c,
            "min": xp_min,
            "max": xp_max,
            "voice_min": xp_voice_min,
            "voice_max": xp_voice_max
        })
    except Exception as e:
        print(f"Error saving XP formula: {e}")
    
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/trigger-backfill")
async def trigger_backfill(request: Request, guild_id: Optional[str] = Form(None), _=Depends(require_admin)):
    """Trigger manual backfill from dashboard (Admin only)."""
    target_gid = guild_id or request.session.get("guild_id") or "615171377783242769"
    
    import subprocess
    import sys
    import os
    
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "backfill_stats.py"))
    token_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "bot_token.py"))
    
    # Read both tokens
    primary_token = None
    dashboard_token = None
    if os.path.exists(token_path):
        with open(token_path, 'r') as f:
            for line in f:
                if line.strip().startswith("TOKEN ="):
                    primary_token = line.split("=")[1].strip().strip('"').strip("'")
                elif line.strip().startswith("DASHBOARD_TOKEN ="):
                    dashboard_token = line.split("=")[1].strip().strip('"').strip("'")
    
    # Determine which token to use based on guild
    # Check bot:guilds in Redis for each bot
    from .utils import get_redis_client
    r = await get_redis_client()
    
    # Get guilds for primary bot (NePornu) - stored in bot:guilds by primary bot
    primary_guilds = await r.smembers("bot:guilds:primary") or set()
    dashboard_guilds = await r.smembers("bot:guilds:dashboard") or set()
    
    # Fallback: use shared bot:guilds and decide based on guild ID
    if not primary_guilds and not dashboard_guilds:
        all_guilds = await r.smembers("bot:guilds")
        # Known primary guilds
        primary_known = {"615171377783242769", "1226095910157680691"}
        if target_gid in primary_known:
            bot_token_val = primary_token
        else:
            bot_token_val = dashboard_token or primary_token
    elif target_gid in primary_guilds:
        bot_token_val = primary_token
    elif target_gid in dashboard_guilds:
        bot_token_val = dashboard_token
    else:
        # Default to dashboard token for new servers (more likely)
        bot_token_val = dashboard_token or primary_token
    
    if os.path.exists(script_path) and bot_token_val:
        cmd = [sys.executable, script_path, "--guild_id", str(target_gid), "--token", bot_token_val]
        
        try:
             subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             return JSONResponse({"status": "ok", "message": f"Backfill started for {target_gid}"})
        except Exception as e:
             return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    else:
         return JSONResponse({"status": "error", "message": "Script or Token not found"}, status_code=500)
@app.get("/api/backfill-status")
async def backfill_status(request: Request, _=Depends(require_admin)):
    """Get the current progress of the backfill process."""
    guild_id = request.session.get("guild_id")
    if not guild_id:
        return JSONResponse({"status": "error", "message": "No guild selected"}, status_code=400)
    
    from .utils import get_redis_client
    r = await get_redis_client()
    
    progress_key = f"backfill:progress:{guild_id}"
    data = await r.get(progress_key)
    
    if not data:
        return JSONResponse({"status": "inactive"})
    
    import json
    return JSONResponse(json.loads(data))


@app.post("/api/delete-server-data")
async def delete_server_data(request: Request, _=Depends(require_admin)):
    """Delete all Redis data for the current server (Admin only)."""
    guild_id = request.session.get("guild_id")
    if not guild_id:
        return JSONResponse({"status": "error", "message": "No guild selected"}, status_code=400)
    
    from .utils import get_redis_client
    r = await get_redis_client()
    
    # Find and delete all keys matching this guild
    patterns = [
        f"stats:*:{guild_id}*",
        f"hll:*:{guild_id}*",
        f"events:*:{guild_id}*",
        f"backfill:*:{guild_id}*",
        f"user:*:{guild_id}*",
        f"daily:*:{guild_id}*",
    ]
    
    deleted_count = 0
    for pattern in patterns:
        keys = []
        async for key in r.scan_iter(pattern):
            keys.append(key)
        if keys:
            deleted_count += await r.delete(*keys)
    
    # Also remove from bot:guilds set
    await r.srem("bot:guilds", guild_id)
    
    return JSONResponse({
        "status": "ok", 
        "message": f"Smazáno {deleted_count} klíčů pro server {guild_id}"
    })


@app.post("/api/leave-server")
async def leave_server(request: Request, _=Depends(require_admin)):
    """Remove bot from current server (Admin only)."""
    guild_id = request.session.get("guild_id")
    if not guild_id:
        return JSONResponse({"status": "error", "message": "No guild selected"}, status_code=400)
    
    import httpx
    import os
    
    # Read token from bot_token.py
    token_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "bot_token.py"))
    primary_token = None
    dashboard_token = None
    if os.path.exists(token_path):
        with open(token_path, 'r') as f:
            for line in f:
                if line.strip().startswith("TOKEN ="):
                    primary_token = line.split("=")[1].strip().strip('"').strip("'")
                elif line.strip().startswith("DASHBOARD_TOKEN ="):
                    dashboard_token = line.split("=")[1].strip().strip('"').strip("'")
    
    # Determine which bot to use
    from .utils import get_redis_client
    r = await get_redis_client()
    primary_known = {"615171377783242769", "1226095910157680691"}
    bot_token = primary_token if guild_id in primary_known else (dashboard_token or primary_token)
    
    if not bot_token:
        return JSONResponse({"status": "error", "message": "Bot token not found"}, status_code=500)
    
    # Discord API: Leave Guild
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"https://discord.com/api/v10/users/@me/guilds/{guild_id}",
            headers={"Authorization": f"Bot {bot_token}"}
        )
        
        if resp.status_code == 204:
            # Also clean up Redis
            await r.srem("bot:guilds", guild_id)
            # Clear session guild
            request.session.pop("guild_id", None)
            request.session.pop("guild_name", None)
            return JSONResponse({"status": "ok", "message": "Bot byl odebrán ze serveru"})
        else:
            return JSONResponse({
                "status": "error", 
                "message": f"Discord API error: {resp.status_code}"
            }, status_code=500)


@app.get("/api/analytics-tools")
async def get_analytics_tools(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None, _=Depends(require_auth)):
    """Get data for analytical tools."""
    guild_id = request.session.get("guild_id")
    if not guild_id:
         return JSONResponse({"status": "error", "message": "No guild selected"}, status_code=400)
    
    from .utils import get_trend_analysis, get_engagement_score, get_insights
    
    try:
        trends = await get_trend_analysis(guild_id)
        engagement = await get_engagement_score(guild_id, start_date=start_date, end_date=end_date)
        insights = await get_insights(guild_id)
        
        return JSONResponse({
            "status": "ok",
            "trends": trends,
            "engagement": engagement,
            "insights": insights
        })
    except Exception as e:
         return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/extended-stats")
async def get_extended_stats(request: Request, start_date: str = None, end_date: str = None, _=Depends(require_auth)):
    """Get extended statistics for new widgets."""
    guild_id = request.session.get("guild_id")
    if not guild_id: return JSONResponse({"status": "error"}, status_code=400)
    
    from .utils import get_deep_stats_redis, get_redis_dashboard_stats, load_member_stats
    
    try:
        # Fetch all necessary data
        # Default to 30 days if not specified
        deep = await get_deep_stats_redis(guild_id, start_date=start_date, end_date=end_date, days=30)
        dash = await get_redis_dashboard_stats(guild_id, start_date=start_date, end_date=end_date)
        growth = await load_member_stats(guild_id, start_date=start_date, end_date=end_date)
        
        # Calculate Hourly Distribution (0-23h) from Heatmap
        # dash['heatmap_data'] is 7x24. Sum columns.
        heatmap = dash.get('heatmap_data', [])
        hourly_dist = [0] * 24
        if heatmap:
            for d in range(7):
                for h in range(24):
                    try: hourly_dist[h] += heatmap[d][h]
                    except: pass
        
        # Calculate Weekend vs Weekday
        # weekly_data in deep is [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
        weekly = deep.get('weekly_data', [0]*7)
        weekday_sum = sum(weekly[0:5])
        weekend_sum = sum(weekly[5:7])
        
        return JSONResponse({
            "status": "ok",
            "hourly_dist": hourly_dist,
            "weekly_dist": weekly,
            "msg_length_dist": deep.get('msglen_data', [0]*5),
            "avg_msg_len": deep.get('avg_msg_len', 0),
            "dates": growth.get('labels', []),
            "growth_total": growth.get('total', []),
            "joins": growth.get('joins', []),
            "leaves": growth.get('leaves', []),
            "weekend_ratio": {"weekday": weekday_sum, "weekend": weekend_sum},
            "stickiness": deep.get('dau_mau_ratio', [])
        })
    except Exception as e:
        print(f"Extended stats error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/export/{export_type}")
@app.get("/api/export/{export_type}")
async def export_data(
    export_type: str, 
    request: Request, 
    format: str = "csv", 
    start_date: str = None, 
    end_date: str = None, 
    _=Depends(require_auth)
):
    """Export server data as CSV or JSON with date filtering."""
    guild_id = request.session.get("guild_id")
    if not guild_id:
         return JSONResponse({"status": "error", "message": "No guild selected"}, status_code=400)
    
    from .utils import get_redis_client, get_activity_stats, get_leaderboard_data, get_channel_distribution
    import io
    import csv
    
    # Generate filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"{export_type}_{guild_id}_{timestamp}"
    
    data_rows = []
    headers = []
    
    try:
        r = await get_redis_client()
        
        if export_type == "leaderboard":
            headers = ["User ID", "Name", "Total Messages", "Avg Length (chars)"]
            
            # Use utility with date filtering
            limit = 1000
            lb_data = await get_leaderboard_data(guild_id, limit=limit, start_date=start_date, end_date=end_date)
            
            for u in lb_data.get("leaderboard", []):
                data_rows.append([u["user_id"], u["name"], u["total_messages"], u["avg_message_length"]])
                
        elif export_type == "voice_top":
            headers = ["User ID", "Name", "Total Seconds", "Hours", "Minutes"]
            # Fetch voice leaderboard
            # Key: stats:voice_duration:{guild_id} (ZSET)
            voice_lb = await r.zrevrange(f"stats:voice_duration:{guild_id}", 0, -1, withscores=True)
            
            # Resolve names
            pipe = r.pipeline()
            for uid, _ in voice_lb:
                pipe.hget(f"user:info:{uid}", "name")
            names = await pipe.execute()
            
            for i, (uid, dur) in enumerate(voice_lb):
                name = names[i] or f"User {uid}"
                dur = int(dur)
                hours = dur // 3600
                minutes = (dur % 3600) // 60
                data_rows.append([uid, name, dur, hours, minutes])

        elif export_type == "commands_top":
            headers = ["Command", "Usage Count"]
            # Key: stats:commands:{guild_id} (HASH)
            cmds = await r.hgetall(f"stats:commands:{guild_id}")
            # Sort by usage
            sorted_cmds = sorted(cmds.items(), key=lambda x: int(x[1]), reverse=True)
            for cmd, count in sorted_cmds:
                data_rows.append([cmd, int(count)])

        elif export_type == "emojis_top":
            headers = ["Emoji", "Usage Count", "Type"]
            # Key: stats:emojis:{guild_id} (ZSET)
            # Assuming it's ZSET based on usage
            emojis = await r.zrevrange(f"stats:emojis:{guild_id}", 0, -1, withscores=True)
            for emo, count in emojis:
                # Emo might be ID or unicode
                e_type = "Custom" if len(str(emo)) > 8 else "Unicode" 
                data_rows.append([str(emo), int(count), e_type])

        elif export_type in ["channels", "channels_top", "channels_full"]:
            headers = ["Channel ID", "Name", "Message Count"]
            
            channels = await get_channel_distribution(guild_id, start_date=start_date, end_date=end_date)
            
            pipe = r.pipeline()
            cids = [c["channel_id"] for c in channels]
            for cid in cids:
                pipe.hget(f"channel:info:{cid}", "name")
            names = await pipe.execute()
            
            for i, c in enumerate(channels):
                name = names[i] or f"Channel {c['channel_id']}"
                data_rows.append([c["channel_id"], name, c["count"]])
        
        elif export_type == "activity":
            # Determine days count from dates if provided, else default 60
            days = 60
            if start_date and end_date:
                try:
                    s = datetime.strptime(start_date, "%Y-%m-%d")
                    e = datetime.strptime(end_date, "%Y-%m-%d")
                    days = (e - s).days + 1
                    if days < 1: days = 1
                except: pass
                
            stats = await get_activity_stats(guild_id, days=days)
            headers = ["Date", "Messages", "Active Users (DAU)"]
            
            labels = stats.get("labels", [])
            # Fix: get_activity_stats date support might be limited or use different keys
            # But the util returns "dau_labels", "dau_data"
            labels = stats.get("dau_labels", [])
            data_points = stats.get("dau_data", [])
            
            for i, label in enumerate(labels):
                d = data_points[i] if i < len(data_points) else 0
                m = 0 # Message count daily history not always in get_activity_stats?
                # Actually main activity chart usually has both.
                # If incomplete, we export what we have (DAU).
                # Messages usually stored in stats:daily_msgs:{date} but we might not have fetched it in that util.
                data_rows.append([label, "N/A", d])

        elif export_type == "users":
            # Detailed user export
            headers = ["User ID", "Name", "Total Messages", "Joined At", "Roles"]
            limit = 1000 # hard limit
            lb_data = await get_leaderboard_data(guild_id, limit=limit, start_date=start_date, end_date=end_date)
            active_users = lb_data.get("leaderboard", [])
            
            pipe = r.pipeline()
            for u in active_users:
                pipe.hgetall(f"user:info:{u['user_id']}")
            infos = await pipe.execute()
            
            for i, u in enumerate(active_users):
                info = infos[i] or {}
                joined = info.get("joined_at", "")
                roles = info.get("roles", "") 
                data_rows.append([u["user_id"], u["name"], u["total_messages"], joined, roles])

        elif export_type == "traffic":
            from .utils import load_member_stats
            headers = ["Month", "Joins", "Leaves", "Total Members"]
            # load_member_stats returns monthly buckets
            m_stats = await load_member_stats(guild_id, start_date=start_date, end_date=end_date)
            labels = m_stats.get("labels", [])
            joins = m_stats.get("joins", [])
            leaves = m_stats.get("leaves", [])
            total = m_stats.get("total", [])
            
            for i, lbl in enumerate(labels):
                j = joins[i] if i < len(joins) else 0
                l = leaves[i] if i < len(leaves) else 0
                t = total[i] if i < len(total) else 0
                data_rows.append([lbl, j, l, t])

        elif export_type == "hourly_heatmap":
            from .utils import get_redis_dashboard_stats
            headers = ["Day/Hour", "Messages Count"]
            # We can use get_redis_dashboard_stats to get heatmap_data (aggregated)
            # OR we can export the raw heat map key
            heatmap = await r.hgetall(f"stats:heatmap:{guild_id}")
            # Key format: "Weekday_Hour" (0-6)_(0-23)
            days_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            
            sorted_keys = sorted(heatmap.keys())
            for k in sorted_keys:
                try:
                    parts = k.split('_')
                    if len(parts) == 2:
                        d, h = int(parts[0]), int(parts[1])
                        d_name = days_map[d] if 0 <= d <= 6 else str(d)
                        count = int(heatmap[k])
                        data_rows.append([f"{d_name} {h:02d}:00", count])
                except: pass

        elif export_type == "msg_lengths":
             headers = ["Length Range", "Count"]
             msg_len_raw = await r.zrange(f"stats:msglen:{guild_id}", 0, -1, withscores=True)
             buckets_map = {0: "0 chars", 5: "1-10 chars", 30: "11-50 chars", 75: "51-100 chars", 150: "101-200 chars", 250: "201+ chars"}
             for bucket, score in msg_len_raw:
                 b_lbl = buckets_map.get(int(float(bucket)), str(bucket))
                 data_rows.append([b_lbl, int(score)])

        elif export_type == "raw_logs":
             # Last 1000 logs (if stored in redis list logs:{gid})
             # Check keys.py or assume "logs:general"
             # If not available, return empty with error message row
             headers = ["Log Entry"]
             data_rows.append(["Log export requires enabled centralized logging."])
             
        else:
             # Generically try to handle or return error
             # For unimplemented "20 more", returning partial data or error is acceptable for V1
             pass

        if not data_rows and export_type not in ["leaderboard", "activity"]:
             data_rows.append(["No data found for this export type or period."])

        # Output Generation
        if format.lower() == "json":
            return {
                "export_type": export_type,
                "generated_at": datetime.now().isoformat(),
                "count": len(data_rows),
                "data": [dict(zip(headers, row)) for row in data_rows]
            }
        else:
            # CSV
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(headers)
            writer.writerows(data_rows)
            
            output.seek(0)
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}.csv"}
            )
            
    except Exception as e:
        print(f"Export error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/logs")
async def get_live_logs(request: Request):
    """API endpoint to get live logs from Redis."""
    try:
        # Connect to Redis
        r = await get_redis_client()
        # Fetch logs
        logs = await r.lrange("dashboard:live_logs", 0, -1)
        # Return newest first
        return {"logs": logs[::-1]}
    except Exception as e:
        return {"logs": [f"Error fetching logs: {e}"]}

@app.get("/api/peak-stats")
async def get_peak_stats_api(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None, role_id: str = "all"):
    """Get peak activity stats."""
    guild_id = get_guild_id(request)
    if not guild_id:
         return {"error": "No guild selected", "peak_analysis": {"peak_hour": "--", "peak_day": "--", "peak_messages": "--", "quiet_period": "--"}}
    
    redis_stats = await get_redis_dashboard_stats(int(guild_id), start_date=start_date, end_date=end_date, role_id=role_id)
    return redis_stats.get("peak_analysis", {
        "peak_hour": "--", "peak_day": "--", "peak_messages": "--", "quiet_period": "--"
    })


@app.get("/api/channel-stats")
async def get_channel_stats(request: Request, start_date=None, end_date=None, role_id="all"):
    """Get per-channel activity statistics."""
    try:
        gid = get_guild_id(request)
        dist = await get_channel_distribution(gid, start_date=start_date, end_date=end_date)
        # Fetch channel names from Discord API or cache
        channels = await get_discord_channels(gid)
        cmap = {str(c['id']): c['name'] for c in channels}
        
        for d in dist:
            d['name'] = cmap.get(str(d['channel_id']), f"#{d['channel_id']}")
            
        return {"channels": dist, "guild_id": gid}
    except Exception as e:
        return {"error": str(e), "channels": [], "guild_id": None}

@app.get("/api/leaderboard")
async def api_leaderboard(request: Request, limit: int = 15, start_date=None, end_date=None, role_id="all"):
    """Get user leaderboard."""
    try:
        gid = get_guild_id(request)
        data = await get_leaderboard_data(gid, limit=limit, start_date=start_date, end_date=end_date)
        data["guild_id"] = gid
        return data
    except Exception as e:
        return {"error": str(e), "leaderboard": [], "guild_id": None}

@app.get("/api/comparisons")
async def api_time_comparisons(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Get WoW and MoM comparisons."""
    try:
        guild_id = get_guild_id(request)
        return await get_time_comparisons(guild_id, start_date=start_date, end_date=end_date)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/security-score")
async def api_security_score(request: Request, _=Depends(require_auth)):
    """Get security score for the current guild."""
    try:
        print("[DEBUG] /api/security-score invoked")
        guild_id = get_guild_id(request)
        print(f"[DEBUG] Calculating score for guild {guild_id}")
        score_data = await get_security_score(guild_id)
        print(f"[DEBUG] Score result: {score_data}")
        return JSONResponse(score_data)
    except HTTPException as he:
        print(f"[ERROR] Security Score HTTP Error: {he.detail}")
        return JSONResponse({"error": he.detail, "overall_score": 0, "rating": "N/A", "components": {}}, status_code=he.status_code)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Security Score Exception: {e}")
        return JSONResponse({"error": str(e), "overall_score": 0, "rating": "Error", "components": {}}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("dashboard.main:app", host="0.0.0.0", port=8092, reload=True)


# --- Helpers ---
def get_guild_id(request: Request, guild_id: Optional[str] = None) -> int:
    """Helper to get guild ID from session or param."""
    gid = request.session.get("guild_id")
    if not gid and guild_id:
        gid = guild_id
    
    print(f"[DEBUG] get_guild_id: session={request.session.get('guild_id')}, param={guild_id} -> Result={gid}")
    
    if not gid:
        raise HTTPException(status_code=400, detail="No guild selected")
    return int(gid)

async def get_discord_channels(guild_id: int):
    """Fetch channels from Discord API."""
    url = f"https://discord.com/api/v10/guilds/{guild_id}/channels"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"Authorization": f"Bot {BOT_TOKEN}"})
        if resp.status_code == 200:
            return resp.json()
    return []

# --- New API Endpoints ---

@app.get("/api/voice-stats")
async def api_voice_stats(
    request: Request, 
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    role_id: str = "all"
):
    """API endpoint for voice leaderboard."""
    gid = get_guild_id(request)
    return await get_voice_leaderboard(gid, limit, start_date=start_date, end_date=end_date, role_id=role_id)

@app.get("/api/command-stats")
async def api_command_stats(
    request: Request, 
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    role_id: str = "all"
):
    """API endpoint for command usage stats."""
    gid = get_guild_id(request)
    return await get_command_stats(gid, limit, start_date=start_date, end_date=end_date, role_id=role_id)

@app.get("/api/traffic-stats")
async def api_traffic_stats(
    request: Request, 
    days: int = 30,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    role_id: str = "all"
):
    """API endpoint for traffic stats (joins/leaves)."""
    gid = get_guild_id(request)
    return await get_traffic_stats(gid, days=days, start_date=start_date, end_date=end_date, role_id=role_id)

@app.get("/api/channel-distribution")
async def api_channel_distribution(request: Request, start_date=None, end_date=None, role_id="all"):
    """DEPRECATED: Redirecting to channel-stats."""
    return await get_channel_stats(request, start_date, end_date, role_id)


