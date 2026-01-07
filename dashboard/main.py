from fastapi import FastAPI, Request, Form, Cookie, Response, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
from pathlib import Path
import redis.asyncio as redis
from datetime import datetime, timedelta
import secrets
import sys
sys.path.append('/root/discord-bot')
try:
    from dashboard_secrets import SECRET_KEY, ACCESS_TOKEN, SESSION_EXPIRY_HOURS
except ImportError:
    SECRET_KEY = secrets.token_urlsafe(32)
    ACCESS_TOKEN = secrets.token_urlsafe(32)
    SESSION_EXPIRY_HOURS = 24
    print(f"WARNING: Using generated secrets. ACCESS_TOKEN={ACCESS_TOKEN}")

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

app = FastAPI(title="NePornu Bot Dashboard", docs_url=None, redoc_url=None)

# Add session middleware for authentication
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_EXPIRY_HOURS * 3600)

# Authentication dependency (runs AFTER middleware)
async def require_auth(request: Request):
    """Check if user is authenticated."""
    # Allow login/static without redirect
    if request.url.path.startswith("/static") or request.url.path in ["/login", "/auth", "/logout"]:
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

# Nastavení cest
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Login routes
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display email login page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/request-otp")
async def request_otp(request: Request, email: str = Form(...)):
    """Request OTP for email."""
    from .otp_utils import validate_email, generate_otp, store_otp, send_otp_email, check_rate_limit, mask_email
    
    # Validate email
    is_valid, message = validate_email(email)
    if not is_valid:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": message}
        )
    
    # Check rate limit
    allowed, remaining = await check_rate_limit(email)
    if not allowed:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": f"Rate limit exceeded. Try again in {remaining} seconds."}
        )
    
    # Generate and store OTP
    otp = generate_otp()
    stored = await store_otp(email, otp)
    
    if not stored:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Error generating OTP. Please try again."}
        )
    
    # Send OTP via email
    sent = await send_otp_email(email, otp)
    
    if not sent:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Error sending email. Please try again."}
        )
    
    # Redirect to verify page
    return templates.TemplateResponse(
        "verify.html",
        {"request": request, "email": email, "masked_email": mask_email(email)}
    )

@app.post("/verify-otp")
async def verify_otp_route(request: Request, email: str = Form(...), otp: str = Form(...)):
    """Verify OTP and create session."""
    from .otp_utils import verify_otp, mask_email
    
    # Verify OTP
    is_valid, message = await verify_otp(email, otp)
    
    if not is_valid:
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "masked_email": mask_email(email), "error": message}
        )
    
    # OTP valid - create session
    request.session["authenticated"] = True
    request.session["login_time"] = datetime.now().isoformat()
    request.session["email"] = email
    
    return RedirectResponse(url="/", status_code=302)

@app.post("/resend-otp")
async def resend_otp(request: Request, email: str = Form(...)):
    """Resend OTP to email."""
    from .otp_utils import generate_otp, store_otp, send_otp_email, check_rate_limit, mask_email
    
    # Check rate limit
    allowed, remaining = await check_rate_limit(email)
    if not allowed:
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": email, "masked_email": mask_email(email), 
             "error": f"Rate limit exceeded. Wait {remaining}s."}
        )
    
    # Generate and send new OTP
    otp = generate_otp()
    await store_otp(email, otp)
    await send_otp_email(email, otp)
    
    return templates.TemplateResponse(
        "verify.html",
        {"request": request, "email": email, "masked_email": mask_email(email),
         "success": "New code sent!"}
    )

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

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    configs = get_challenge_config()
    target_gid = list(configs.keys())[0] if configs else ""
    current_cfg = configs.get(target_gid, {})
    
    return templates.TemplateResponse(
        "settings.html", 
        {
            "request": request,
            "config_json": configs,
            "target_gid": target_gid,
            "current_cfg": current_cfg
        }
    )

@app.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    guild_id: str = Form(...),
    role_id: str = Form(...),
    channel_id: str = Form(...),
    emojis: str = Form(...),
):
    configs = get_challenge_config()
    if guild_id not in configs: configs[guild_id] = {}
        
    cfg = configs[guild_id]
    cfg["guild_id"] = int(guild_id)
    cfg["role_id"] = int(role_id) if role_id.isdigit() else None
    cfg["channel_id"] = int(channel_id) if channel_id.isdigit() else None
    
    raw_emojis = emojis.replace(",", " ").split()
    cfg["emojis"] = [e.strip() for e in raw_emojis if e.strip()]
    
    configs[guild_id] = cfg
    save_challenge_config(configs)
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "target_gid": guild_id,
            "current_cfg": cfg,
            "message": "✅ Nastavení uloženo (Bot restart nutný!)",
            "config_json": configs
        }
    )

@app.get("/commands", response_class=HTMLResponse)
async def commands_page(request: Request, _=Depends(require_auth)):
    return templates.TemplateResponse("commands.html", {"request": request})

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, _=Depends(require_auth)):
    """New advanced analytics page with channel stats and leaderboards."""
    return templates.TemplateResponse("analytics.html", {"request": request})


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
