from fastapi import FastAPI, Request, Form, Cookie, Response, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
from pathlib import Path
import redis.asyncio as redis
from datetime import datetime, timedelta
from collections import defaultdict
import secrets
import httpx
import sys
sys.path.append('/root/discord-bot')
try:
    from dashboard_secrets import (
        SECRET_KEY, ACCESS_TOKEN, SESSION_EXPIRY_HOURS,
        DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
        ADMIN_USER_IDS
    )
except ImportError:
    SECRET_KEY = secrets.token_urlsafe(32)
    ACCESS_TOKEN = secrets.token_urlsafe(32)
    SESSION_EXPIRY_HOURS = 24
    DISCORD_CLIENT_ID = ""
    DISCORD_CLIENT_SECRET = ""
    DISCORD_REDIRECT_URI = "http://localhost:8092/auth/callback"
    ADMIN_USER_IDS = []
    print(f"WARNING: Using generated secrets.")

from .utils import (
    load_member_stats, 
    get_activity_stats, 
    get_deep_stats,
    get_challenge_config, 
    save_challenge_config,
    get_realtime_online_count,
    get_summary_card_data,
    get_redis_dashboard_stats
)

app = FastAPI(title="Bot Dashboard", docs_url=None, redoc_url=None)

# Add session middleware for authentication (same_site=lax for OAuth redirects)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_EXPIRY_HOURS * 3600, same_site="lax", https_only=False)

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

# Nastavení cest
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Discord OAuth2 routes
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

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
        
        # Store in session - MINIMAL DATA ONLY to prevent cookie overflow
        request.session["authenticated"] = True
        request.session["login_time"] = datetime.now().isoformat()
        
        # Only store essential user info
        request.session["discord_user"] = {
            "id": user_data["id"],
            "username": user_data.get("global_name") or user_data["username"],
            # Avatars are just strings but let's keep it small
            "avatar": user_data.get("avatar")
        }
        
        # DO NOT STORE GUILDS IN COOKIE - IT IS TOO LARGE
        # We will fetch them/store in Redis later if needed
        # request.session["guilds"] = [{"id": g["id"], "name": g["name"], "icon": g.get("icon")} for g in guilds_data]
        
        request.session["role"] = "admin" if is_admin else "guest"
        
        # Save session intentionally
        
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
    return RedirectResponse(url="/login", status_code=302)

# Exception handler for 401 (redirect to login)
@app.exception_handler(401)
async def redirect_to_login_handler(request: Request, exc: HTTPException):
    return RedirectResponse(url="/login", status_code=302)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, _=Depends(require_auth)):
    # 1. Member Growth & Flow
    member_stats = load_member_stats()
    
    # 2. Activity (DAU/MAU)
    activity_stats = get_activity_stats()
    
    # 3. Deep Stats (Retention, Weekday, WAU - all real data)
    # We pass raw_data from activity_stats to avoid re-reading
    deep_stats = get_deep_stats(activity_stats.get("raw_data", {}))
    
    # 3b. Redis Dashboard Stats (Real data for hourly, heatmap, message lengths)
    redis_stats = await get_redis_dashboard_stats()
    deep_stats.update(redis_stats)  # Merge real data into deep_stats
    
    # 4. Realtime Snapshot (actual online members)
    realtime_active = await get_realtime_online_count()
    
    # KPIs & Extract current values for Summary Card
    total_leaves = sum(member_stats["leaves"])
    current_total = member_stats["total"][-1] if member_stats["total"] else 0
    
    current_dau = activity_stats["dau_data"][-1] if activity_stats["dau_data"] else 0
    current_mau = activity_stats["mau_data"][-1] if activity_stats["mau_data"] else 0
    current_wau = deep_stats.get("wau_data", [])[-1] if deep_stats.get("wau_data") else 0
    
    # Summary Card Data (ONLY real stats - no placeholders)
    summary_stats = await get_summary_card_data(
        discord_dau=current_dau,
        discord_mau=current_mau,
        discord_wau=current_wau,
        discord_users=current_total, # strict function will prefer Redis data anyway
        guild_id=615171377783242769
    )
    
    # Calculate churn using REAL total members
    real_total_members = summary_stats["discord"]["users"]
    churn_rate = round((total_leaves / max(1, real_total_members)) * 100, 2)
    
    # 5. Render Template
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            # Summary Top Section
            "summary_stats": summary_stats,
            "realtime_active": realtime_active,
            "total_members": real_total_members,
            "churn_rate": churn_rate,
            "avg_dau": round(sum(activity_stats["dau_data"][-30:]) / 30, 1) if activity_stats["dau_data"] else 0,
            
            # Basic Charts
            "labels": member_stats["labels"],
            "total_data": member_stats["total"],
            "joins_data": member_stats["joins"],
            "leaves_data": member_stats["leaves"],
            
            "dau_labels": activity_stats["dau_labels"],
            "dau_data": activity_stats["dau_data"],
            "mau_labels": activity_stats["mau_labels"],
            "mau_data": activity_stats["mau_data"],
            
            # Deep Charts
            "retention_labels": deep_stats.get("retention_labels", []),
            "new_users": deep_stats.get("new_users", []),
            "returning_users": deep_stats.get("returning_users", []),
            "weekday_labels": deep_stats.get("weekday_labels", []),
            "weekday_data": deep_stats.get("weekday_data", []),
            "weekend_vs_workday": deep_stats.get("weekend_vs_workday", [0, 0]),
            "leaderboard": deep_stats.get("leaderboard", []),
            
            # New Extracted Stats
            "wau_data": deep_stats.get("wau_data", []),
            "dau_wau_ratio": deep_stats.get("dau_wau_ratio", []),
            "dau_mau_ratio": deep_stats.get("dau_mau_ratio", []),
            "hourly_activity": deep_stats.get("hourly_activity", []),
            "hourly_labels": deep_stats.get("hourly_labels", []),
            "msg_len_hist_labels": deep_stats.get("msg_len_hist_labels", []),
            "msg_len_hist_data": deep_stats.get("msg_len_hist_data", []),
            "avg_msg_len_hourly": deep_stats.get("avg_msg_len_hourly", []),
            "heatmap_data": deep_stats.get("heatmap_data", []),
            "heatmap_max": deep_stats.get("heatmap_max", 1),
            "cumulative_msgs": deep_stats.get("cumulative_msgs", []),
            "current_date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            
            # KPIs
            "realtime_active": realtime_active,
            "avg_dau": activity_stats["avg_dau"],
            "churn_rate": churn_rate
        }
    )

# Challenge config routes moved - /settings is now for action weights

@app.get("/commands", response_class=HTMLResponse)
async def commands_page(request: Request, _=Depends(require_auth)):
    return templates.TemplateResponse("commands.html", {"request": request})

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, _=Depends(require_auth)):
    """New advanced analytics page with channel stats and leaderboards."""
    return templates.TemplateResponse("analytics.html", {"request": request})

@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request, start_date: str = None, end_date: str = None, role_id: str = None, _=Depends(require_auth)):
    """Moderator Activity Page with manual Redis aggregation."""
    
    # Check role - guests see restricted view
    user_role = request.session.get("role", "guest")
    if user_role != "admin":
        return templates.TemplateResponse("activity_restricted.html", {
            "request": request,
            "message": "Přístup k této stránce je omezen. Pro přístup ke svým guildám kontaktujte administrátora."
        })
    
    # Parse dates
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

    days_map = {} 
    user_map = {} 
    
    top_action = "N/A"
    total_sec_30d = 0
    available_roles = {}
    
    try:
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        gid = 615171377783242769
        
        # 1. Fetch Available Roles
        available_roles = await r.hgetall(f"guild:roles:{gid}")
        
        # 2. Discover Active Users (from event keys)
        active_users = set()
        for pattern in [f"events:msg:{gid}:*", f"events:voice:{gid}:*", f"events:action:{gid}:*"]:
            async for key in r.scan_iter(pattern):
                # Extract UID from key: events:TYPE:GID:UID
                parts = key.split(":")
                if len(parts) == 4:
                    active_users.add(int(parts[3]))
        
        # 3. Iterate Through Days & Users
        current_day = d_start
        while current_day <= d_end:
            day_str = current_day.strftime("%Y-%m-%d")
            
            for uid in active_users:
                daily_stats = await get_daily_stats(r, gid, uid, current_day)
                
                if not daily_stats: continue  # No data this day
                
                # Aggregate into daily totals
                if day_str not in days_map: days_map[day_str] = 0
                
                # Calculate weighted time
                chat_t = daily_stats.get("chat_time", 0)
                voice_t = daily_stats.get("voice_time", 0)
                
                # Action time
                weights = await get_action_weights(r)
                action_t = 0
                for action_metric in ["bans", "kicks", "timeouts", "unbans", "verifications", "msg_deleted", "role_updates"]:
                    action_t += daily_stats.get(action_metric, 0) * weights.get(action_metric, 0)
                
                weighted_total = chat_t + voice_t + action_t
                days_map[day_str] += (weighted_total / 3600)
                
                # Aggregate into user totals
                if uid not in user_map:
                    user_map[uid] = {"weighted": 0, "chat": 0, "voice": 0, "actions": 0, "name": f"User {uid}", "avatar": "", "roles": ""}
                
                user_map[uid]["weighted"] += weighted_total
                user_map[uid]["chat"] += chat_t
                user_map[uid]["voice"] += voice_t
                user_map[uid]["actions"] += action_t
                
                total_sec_30d += weighted_total
            
            current_day += timedelta(days=1)

        # 3. Resolve Usernames & Roles
        try:
            p = r.pipeline()
            uids = list(user_map.keys())
            for uid in uids:
                p.hgetall(f"user:info:{uid}")
            
            results = await p.execute()
            
            for i, uid in enumerate(uids):
                info = results[i]
                if info and "name" in info:
                    user_map[uid]["name"] = info["name"]
                    user_map[uid]["avatar"] = info.get("avatar", "")
                    user_map[uid]["roles"] = info.get("roles", "") # Comma separated IDs
        except Exception as e:
            print(f"Error resolving names: {e}")

        await r.aclose()
        
    except Exception as e:
        print(f"Error fetching activity: {e}")
        
    # Format for Charts
    sorted_days = sorted(days_map.keys())
    daily_labels = [d[5:] for d in sorted_days]
    daily_hours = [round(days_map[d], 1) for d in sorted_days]
    
    # Format Leaderboard & Filter by Role
    leaderboard = []
    for uid, data in user_map.items():
        # Role Filter
        if role_id and role_id != "all":
            user_roles = data["roles"].split(",")
            if str(role_id) not in user_roles:
                continue
        
        leaderboard.append({
            "uid": uid,
            "name": data["name"],
            "avatar": data.get("avatar", ""),
            "weighted_h": round(data["weighted"] / 3600, 1),
            "chat_h": round(data["chat"] / 3600, 1),
            "voice_h": round(data["voice"] / 3600, 1),
            "actions": int(data["actions"])
        })
    
    leaderboard.sort(key=lambda x: x["weighted_h"], reverse=True)
    
    # Sort roles for dropdown
    sorted_roles = sorted(available_roles.items(), key=lambda x: x[1])
    
    return templates.TemplateResponse(
        "activity.html", 
        {
            "request": request,
            "daily_labels": daily_labels,
            "daily_hours": daily_hours,
            "leaderboard": leaderboard[:100], 
            "total_hours_30d": round(total_sec_30d / 3600, 1),
            "active_staff_count": len(leaderboard),
            "top_action": "Chatting",
            "start_date": d_start.strftime("%Y-%m-%d"),
            "end_date": d_end.strftime("%Y-%m-%d"),
            "roles": sorted_roles,
            "selected_role": role_id or "all"
        }
    )

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
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
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

        await r.aclose()
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

    return templates.TemplateResponse(
        "user_activity.html",
        {
            "request": request,
            "user_info": user_info,
            "user_roles": user_info["roles"],
            "daily_labels": daily_labels,
            "daily_values": daily_values,
            "total_time_h": total_h,
            "chat_time_h": chat_h,
            "voice_time_h": voice_h,
            "user_stats": stats_summary,
            "action_breakdown": action_breakdown,
            "total_actions": total_actions,
            "start_date": d_start.strftime("%Y-%m-%d"),
            "end_date": d_end.strftime("%Y-%m-%d")
        }
    )


# --- HELPER: Action Weights ---
async def get_action_weights(r: redis.Redis) -> dict:
    """Fetch action weights from Redis or use defaults."""
    # Defaults
    defaults = {
        "bans": 300, "kicks": 180, "timeouts": 180, "unbans": 120, 
        "verifications": 120, "msg_deleted": 60, "role_updates": 30,
        "chat_time": 1, "voice_time": 1
    }
    
    try:
        stored = await r.hgetall("config:action_weights")
        if stored:
            # Merge stored values (convert to int)
            for k, v in stored.items():
                if k in defaults:
                    defaults[k] = int(v)
    except Exception as e:
        print(f"Error fetching weights: {e}")
        
    return defaults

async def get_daily_stats(r: redis.Redis, gid: int, uid: int, day: datetime.date) -> dict:
    """
    Get daily stats for a user on a specific day.
    Uses cached value if version matches, otherwise recalculates from raw events.
    """
    from datetime import datetime as dt
    import json
    from collections import defaultdict
    
    day_str = day.strftime("%Y-%m-%d")
    cache_key = f"stats:day:{day_str}:{gid}:{uid}"
    
    # Check cache version
    cached_version = await r.hget(cache_key, "_version")
    current_version = await r.get("config:weights_version") or "0"
    
    if cached_version == current_version:
        # Cache hit!
        stats = await r.hgetall(cache_key)
        # Convert strings to floats/ints
        return {k: float(v) if k != "_version" else v for k, v in stats.items()}
    
    # Cache miss → recalculate from raw events
    weights = await get_action_weights(r)
    
    # Timestamp range for this day
    from datetime import time as dt_time
    day_start = dt.combine(day, dt_time(0, 0, 0)).timestamp()
    day_end = dt.combine(day, dt_time(23, 59, 59)).timestamp()
    
    stats = defaultdict(float)
    
    # 1. Messages
    msg_key = f"events:msg:{gid}:{uid}"
    messages = await r.zrangebyscore(msg_key, day_start, day_end)
    
    for msg_json in messages:
        msg_data = json.loads(msg_json)
        stats["messages"] += 1
        stats["chat_time"] += msg_data["len"] * weights.get("chat_time", 1)
    
    # 2. Voice
    voice_key = f"events:voice:{gid}:{uid}"
    voice_sessions = await r.zrangebyscore(voice_key, day_start, day_end)
    
    for vs_json in voice_sessions:
        vs_data = json.loads(vs_json)
        stats["voice_time"] += vs_data["duration"] * weights.get("voice_time", 1)
    
    # 3. Actions
    action_key = f"events:action:{gid}:{uid}"
    actions = await r.zrangebyscore(action_key, day_start, day_end)
    
    for action_json in actions:
        action_data = json.loads(action_json)
        action_type = action_data["type"]
        
        # Map back to old metric names for compatibility
        metric_map = {
            "ban": "bans", "kick": "kicks", "timeout": "timeouts",
            "unban": "unbans", "role_update": "role_updates",
            "msg_delete": "msg_deleted"
        }
        
        metric = metric_map.get(action_type, action_type + "s")
        stats[metric] += 1
    
    # Store in cache with version
    cache_data = dict(stats)
    cache_data["_version"] = current_version
    await r.hset(cache_key, mapping={k: str(v) for k, v in cache_data.items()})
    
    return dict(stats)

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, _=Depends(require_admin)):
    """Settings page for configuring weights (admin only)."""
    # Defaults
    weights = {
        "bans": 300, "kicks": 180, "timeouts": 180, "unbans": 120, 
        "verifications": 120, "msg_deleted": 60, "role_updates": 30,
        "chat_time": 1, "voice_time": 1
    }
    
    try:
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        weights = await get_action_weights(r)
        await r.aclose()
    except Exception as e:
        print(f"Error loading settings: {e}")
        # Keep defaults on error
        
    return templates.TemplateResponse("settings.html", {"request": request, "weights": weights})

@app.post("/settings/weights")
async def update_weights(
    request: Request,
    bans: int = Form(...), kicks: int = Form(...), timeouts: int = Form(...),
    unbans: int = Form(...), verifications: int = Form(...), 
    msg_deleted: int = Form(...), role_updates: int = Form(...),
    chat_time: int = Form(...), voice_time: int = Form(...),
    _=Depends(require_auth)
):
    """Update action weights in Redis."""
    try:
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        
        mapping = {
            "bans": bans, "kicks": kicks, "timeouts": timeouts,
            "unbans": unbans, "verifications": verifications,
            "msg_deleted": msg_deleted, "role_updates": role_updates,
            "chat_time": chat_time, "voice_time": voice_time
        }
        
        await r.hset("config:action_weights", mapping=mapping)
        
        # INVALIDATE ALL CACHED STATS
        await r.incr("config:weights_version")
        
        await r.aclose()
        
    except Exception as e:
        print(f"Error saving weights: {e}")
        
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/api/logs")
async def get_live_logs(request: Request):
    """API endpoint to get live logs from Redis."""
    try:
        # Connect to Redis
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        # Fetch logs
        logs = await r.lrange("dashboard:live_logs", 0, -1)
        await r.aclose()
        # Return newest first
        return {"logs": logs[::-1]}
    except Exception as e:
        return {"logs": [f"Error fetching logs: {e}"]}

@app.get("/api/channel-stats")
async def get_channel_stats(request: Request, guild_id: int = 615171377783242769, days: int = 30):
    """Get per-channel activity statistics."""
    try:
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        from datetime import timedelta
        
        # Get total messages per channel (all-time)
        channel_totals = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, -1, withscores=True)
        
        # Get channel names from bot (requires Discord API lookup - simplified for now)
        channel_data = []
        for channel_id_str, total_msgs in channel_totals:
            channel_id = int(float(channel_id_str))
            channel_data.append({
                "channel_id": channel_id,
                "total_messages": int(total_msgs),
                "name": f"channel-{channel_id}"  # Placeholder - would fetch from Discord API
            })
        
        await r.aclose()
        return {"channels": channel_data[:20]}  # Top 20
    except Exception as e:
        return {"error": str(e), "channels": []}

@app.get("/api/leaderboard")
async def get_leaderboard(request: Request, guild_id: int = 615171377783242769, limit: int = 10):
    """Get user leaderboard (top contributors)."""
    try:
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        
        # Get top users by message count
        top_users = await r.zrevrange(f"leaderboard:messages:{guild_id}", 0, limit - 1, withscores=True)
        
        leaderboard = []
        for user_id_str, msg_count in top_users:
            user_id = int(float(user_id_str))
            
            # Calculate average message length
            msg_lengths = await r.lrange(f"leaderboard:msg_lengths:{guild_id}:{user_id}", 0, -1)
            if msg_lengths:
                avg_len = sum(int(l) for l in msg_lengths) / len(msg_lengths)
            else:
                avg_len = 0
            
            leaderboard.append({
                "user_id": user_id,
                "total_messages": int(msg_count),
                "avg_message_length": round(avg_len, 1),
                "name": f"User#{user_id}"  # Placeholder - would fetch from Discord API
            })
        
        await r.aclose()
        return {"leaderboard": leaderboard}
    except Exception as e:
        return {"error": str(e), "leaderboard": []}

@app.get("/api/comparisons")
async def get_time_comparisons(request: Request, guild_id: int = 615171377783242769):
    """Get week-over-week and month-over-month comparisons."""
    try:
        # Simplified - would calculate from DAU/MAU data
        activity_stats = get_activity_stats()
        
        # Get last 2 weeks avg
        dau_data = activity_stats.get("dau_data", [])
        if len(dau_data) >= 14:
            this_week = sum(dau_data[-7:]) / 7
            last_week = sum(dau_data[-14:-7]) / 7
            wow_change = ((this_week - last_week) / max(1, last_week)) * 100
        else:
            this_week, last_week, wow_change = 0, 0, 0
        
        # Get last 2 months avg
        if len(dau_data) >= 60:
            this_month = sum(dau_data[-30:]) / 30
            last_month = sum(dau_data[-60:-30]) / 30
            mom_change = ((this_month - last_month) / max(1, last_month)) * 100
        else:
            this_month, last_month, mom_change = 0, 0, 0
        
        return {
            "week_over_week": {
                "this_week": round(this_week, 1),
                "last_week": round(last_week, 1),
                "change_percent": round(wow_change, 1)
            },
            "month_over_month": {
                "this_month": round(this_month, 1),
                "last_month": round(last_month, 1),
                "change_percent": round(mom_change, 1)
            }
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    uvicorn.run("dashboard.main:app", host="0.0.0.0", port=8092, reload=True)
