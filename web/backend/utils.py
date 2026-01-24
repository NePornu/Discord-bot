import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict, Counter
import redis.asyncio as redis
import httpx
import sys
sys.path.append('/root/discord-bot')

# Import centralized Redis client
from shared.redis_client import get_redis, REDIS_URL

try:
    from config.dashboard_secrets import BOT_TOKEN
except ImportError:
    BOT_TOKEN = ""

DATA_DIR = Path("data")
CONFIG_PATH = DATA_DIR / "challenge_config.json"

# Helper for backwards compatibility - gradually migrate to shared.redis_client
async def get_redis_client() -> redis.Redis:
    """Get Redis client from centralized pool."""
    return await get_redis()

async def load_member_stats(guild_id: int, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """
    Načte Member Growth data z Redis (Joins/Leaves) a filtruje podle data.
    """
    r = await get_redis()
    try:
        # Fetch joins and leaves hashes
        joins_data = await r.hgetall(f"stats:joins:{guild_id}")
        leaves_data = await r.hgetall(f"stats:leaves:{guild_id}")
        
        # Merge keys (months)
        all_keys = set(joins_data.keys()) | set(leaves_data.keys())
        sorted_keys = sorted(all_keys)
        
        cumulative_count = 0 
        
        # Calculate initial count for the start period
        if start_date:
             start_ym = start_date[:7]
             for k in sorted_keys:
                 if k < start_ym:
                     j = int(joins_data.get(k, 0))
                     l = int(leaves_data.get(k, 0))
                     cumulative_count += (j - l)
                 else:
                     break
        
        total_counts = []
        joins = []
        leaves = []
        
        labels = []
        for k in sorted_keys:
            # Filter by date if provided (keys are "YYYY-MM")
            # We already advanced cumulative_count up to start_date
            if start_date and k < start_date[:7]: continue
            if end_date and k > end_date[:7]: continue

            j = int(joins_data.get(k, 0))
            l = int(leaves_data.get(k, 0))
            net = j - l
            cumulative_count += net
            
            total_counts.append(cumulative_count)
            joins.append(j)
            leaves.append(l)
            labels.append(k)

        return {
            "labels": labels,
            "total": total_counts,
            "joins": joins,
            "leaves": leaves
        }
    except Exception as e:
        print(f"Error loading member stats from Redis: {e}")
        return {"labels": [], "total": [], "joins": [], "leaves": []}
    finally:
        pass

async def get_activity_stats(guild_id: int, start_date: str = None, end_date: str = None, days: int = 30) -> Dict[str, Any]:
    """
    Základní aktivita: DAU, MAU, Avg DAU - podpora pro časové období.
    """
    r = await get_redis()
    try:
        # Date logic
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        elif end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=days-1)
        else:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days-1)

        date_list = []
        curr = start_dt
        while curr <= end_dt:
            date_list.append(curr)
            curr += timedelta(days=1)

        # PIPELINE OPTIMIZATION
        pipe = r.pipeline()
        debug_keys = []
        for d in date_list:
            d_str = d.strftime("%Y%m%d")
            k = f"hll:dau:{guild_id}:{d_str}"
            pipe.pfcount(k)
            debug_keys.append(k)
        
        results = await pipe.execute()
        print(f"[DEBUG] get_activity_stats: Guild={guild_id}, Keys={debug_keys[:3]}...{debug_keys[-1]}, Results={results}, Sum={sum(results)}")
        
        dau_data = results
        dau_labels = [d.strftime("%Y-%m-%d") for d in date_list]
            
        avg_dau = sum(dau_data) / len(dau_data) if dau_data else 0
        
        return {
            "dau_labels": dau_labels,
            "dau_data": dau_data,
            "mau_labels": [],
            "mau_data": [],
            "avg_dau": round(avg_dau, 1),
            "raw_data": {}
        }
    except Exception as e:
        print(f"Error parsing activity stats: {e}")
        return {"dau_labels": [], "dau_data": [], "mau_labels": [], "mau_data": [], "avg_dau": 0, "raw_data": {}}
    finally:
        pass

    # ... (removed get_deep_stats implementation as it's now integrated or needs to be Redis-based)
    # We will compute deeper stats inside get_dashboard_redis_stats or a new async function

async def get_deep_stats_redis(guild_id: int, days: int = 30, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """
    Calculate advanced stats (Retention, Stickiness) using Redis HLLs.
    Computed on-the-fly or cached.
    """
    r = await get_redis()
    cache_key = f"stats:cache:deep:{guild_id}:{start_date}:{end_date}:v3"
    
    try:
        # Determine date list first
        if start_date and end_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                
                date_list = []
                curr = start_dt
                while curr <= end_dt:
                    date_list.append(curr)
                    curr += timedelta(days=1)
                date_list.sort()
            except ValueError:
                 now = datetime.now()
                 date_list = [now - timedelta(days=i) for i in range(days)]
                 date_list.sort()
        else:
            now = datetime.now()
            date_list = [now - timedelta(days=i) for i in range(days)]
            date_list.sort() # Oldest first

        # Check cache (only if standard 30 days request)
        if not start_date and days == 30:
             cached = await r.get(cache_key)
             if cached: return json.loads(cached)
        
        # Calculate WAU and Ratios
        wa_data = []
        dau_wau_ratio = []
        dau_mau_ratio = []
        retention_labels = []
        
        wau_data = []

        # Iterate date_list
        # date_list is sorted Oldest -> Newest
        for d in date_list:
             # d is datetime object
            d_str = d.strftime("%Y%m%d")
            d_label = d.strftime("%Y-%m-%d")
            
            # Current DAU
            k_today = f"hll:dau:{guild_id}:{d_str}"
            dau = await r.pfcount(k_today)
            
            # WAU (Today + last 6 days)
            wau_keys = [f"hll:dau:{guild_id}:{(d - timedelta(days=j)).strftime('%Y%m%d')}" for j in range(7)]
            wau = await r.pfcount(*wau_keys)
            
            # MAU (Today + last 29 days)
            mau_keys = [f"hll:dau:{guild_id}:{(d - timedelta(days=j)).strftime('%Y%m%d')}" for j in range(30)]
            mau = await r.pfcount(*mau_keys)
            
            wau_data.append(wau)
            
            dw_ratio = (dau / wau * 100) if wau > 0 else 0
            dau_wau_ratio.append(round(dw_ratio, 1))
            
            dm_ratio = (dau / mau * 100) if mau > 0 else 0
            dau_mau_ratio.append(round(dm_ratio, 1))
            
            retention_labels.append(d_label)
            
        # Retention (New vs Returning)
        # Hard with just HLL. We might have to skip or mock for now.
        # Or just show DAU as "Active Users".
        
        # New Charts Data: Message Length Distribution
        # stats:msglen:GID (ZSET: bucket -> count)
        msglen_raw = await r.zrange(f"stats:msglen:{guild_id}", 0, -1, withscores=True)
        # buckets: 0, 5, 30, 75, 150, 250
        buckets_map = {0: 5, 5: 10, 30: 30, 75: 75, 150: 150, 250: 300}
        
        msglen_data = [0, 0, 0, 0, 0]
        total_len = 0
        total_msgs = 0
        
        # Hist mapping matched to backfill buckets
        # backfill uses: 0, 10, 50, 100, 200, 250+
        # Wait, let's look at backfill_stats.py:136 again:
        # if msg_len == 0: b=0
        # elif msg_len <= 10: b=5
        # elif msg_len <= 50: b=30
        # elif msg_len <= 100: b=75
        # elif msg_len <= 200: b=150
        # else: b=250
        
        for buck_str, score in msglen_raw:
             try:
                 bucket = int(float(buck_str))
                 cnt = int(score)
                 total_msgs += cnt
                 total_len += cnt * bucket
                 
                 if bucket == 0: continue # ignore empty
                 elif bucket == 5: msglen_data[0] += cnt
                 elif bucket == 30: msglen_data[1] += cnt
                 elif bucket == 75: msglen_data[2] += cnt
                 elif bucket == 150: msglen_data[3] += cnt
                 elif bucket == 250: msglen_data[4] += cnt
             except: pass
        
        avg_msg_len = round(total_len / max(1, total_msgs))
        
        # Weekly Activity: Sum heatmap rows to get per-weekday totals
        heatmap = await r.hgetall(f"stats:heatmap:{guild_id}")
        weekly_data = [0, 0, 0, 0, 0, 0, 0]
        weekday_names = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
        for key, val in heatmap.items():
            parts = key.split("_")
            if len(parts) == 2:
                weekday, hour = int(parts[0]), int(parts[1])
                if 0 <= weekday < 7:
                    weekly_data[weekday] += int(val)
        
        # Peak day calculation
        peak_day_idx = weekly_data.index(max(weekly_data)) if max(weekly_data) > 0 else 0
        peak_day = weekday_names[peak_day_idx]
        peak_day_count = weekly_data[peak_day_idx]
        
        # Reply ratio (estimate from events, if available)
        # For now, set a default until we collect reply data
        reply_ratio = 15  # Default estimate
        
        stats = {
            "wau_data": wau_data,
            "dau_wau_ratio": dau_wau_ratio,
            "dau_mau_ratio": dau_mau_ratio,
            "retention_labels": retention_labels, 
            "returning_users": [],
            "new_users": [],
            "weekday_data": [], # Can be calc from Redis if needed
            "weekly_labels": ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"],
            # New chart data
            "msglen_data": msglen_data,
            "weekly_data": weekly_data,
            "avg_msg_len": avg_msg_len,
            "peak_day": peak_day,
            "peak_day_count": peak_day_count,
            "reply_ratio": reply_ratio,
        }
        
        await r.setex(cache_key, 600, json.dumps(stats))
        return stats
        
    except Exception as e:
        print(f"Redis stats error: {e}")

        return {}
    finally:
        pass
    #     pass


async def get_redis_dashboard_stats(guild_id: int, start_date: str = None, end_date: str = None, role_id: str = None) -> Dict[str, Any]:
    """
    Fetch dashboard statistics directly from Redis (Real-time).
    """
    r = await get_redis()
    cache_key = f"stats:cache:dashboard:{guild_id}:{start_date}:{end_date}:{role_id}:v4"
    
    try:
        # Check cache
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)

        # 1. Hourly Pattern (Last 24h?) No, aggregate "Daily Hourly"
        # We want to show "Average Hourly Activity"
        # stats:hourly:GID:DATE stores counts for that day.
        # Let's aggregate last 7 days.
        # Date logic
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=29)

        date_list = []
        curr = start_dt
        while curr <= end_dt:
            date_list.append(curr)
            curr += timedelta(days=1)
        
        hourly_counts = [0] * 24
        
        # PIPELINE OPTIMIZATION
        pipe = r.pipeline()
        for d in date_list:
            d_str = d.strftime("%Y%m%d")
            pipe.hgetall(f"stats:hourly:{guild_id}:{d_str}")
        
        hashes = await pipe.execute()
        for h_data in hashes:
            if h_data:
                for h, c in h_data.items():
                    try: hourly_counts[int(h)] += int(float(c))
                    except: pass
        
        # Use total counts (not average) - more meaningful for visualizing patterns
        # hourly_counts already has the totals from last 30 days

        # 2. Heatmap (Accumulated from hourly data)
        heatmap_data = [[0 for _ in range(24)] for _ in range(7)]
        if hashes:
            for i, h_data in enumerate(hashes):
                if h_data:
                    day_idx = date_list[i].weekday()
                    for h, c in h_data.items():
                        try: heatmap_data[day_idx][int(h)] += int(float(c))
                        except: pass
        
        # 3. Peak Analysis Calculation
        peak_hour, peak_day, peak_msgs = "--", "--", "--"
        quiet_period = "--"
        
        if any(any(row) for row in heatmap_data):
            # Flatten for peak calculations
            hour_totals = [0] * 24
            day_totals = [0] * 7
            for w in range(7):
                for h in range(24):
                    val = heatmap_data[w][h]
                    hour_totals[h] += val
                    day_totals[w] += val
            
            # Find Peaks
            p_h_idx = hour_totals.index(max(hour_totals))
            peak_hour = f"{p_h_idx:02d}:00"
            
            p_d_idx = day_totals.index(max(day_totals))
            days_cz = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
            peak_day = days_cz[p_d_idx]
            
            peak_msgs = max(day_totals) # Max daily messages
            
            # Quietest 2-hour window
            min_sum = float('inf')
            quiet_start = 0
            for h in range(23):
                window_sum = hour_totals[h] + hour_totals[h+1]
                if window_sum < min_sum:
                    min_sum = window_sum
                    quiet_start = h
            # Check rollover 23-00
            if (hour_totals[23] + hour_totals[0]) < min_sum:
                quiet_start = 23
                
            quiet_end = (quiet_start + 2) % 24
            quiet_period = f"{quiet_start:02d}:00-{quiet_end:02d}:00"
            
            if peak_msgs == 0:
                 peak_hour, peak_day, peak_msgs, quiet_period = "--", "--", "--", "--"
                 
        heatmap_max = max(max(row) for row in heatmap_data) if heatmap_data else 1

        # 3. Message Lengths
        # stats:msglen:GID (ZSET: bucket -> count)
        msg_len_raw = await r.zrange(f"stats:msglen:{guild_id}", 0, -1, withscores=True)
        # buckets: 0, 5, 30, 75, 150, 250
        buckets_map = {0: "0", 5: "1-10", 30: "11-50", 75: "51-100", 150: "101-200", 250: "201+"}
        
        # Initialize
        hist_data = {k: 0 for k in buckets_map.keys()}
        
        for buck_str, score in msg_len_raw:
             try: hist_data[int(float(buck_str))] = int(score)
             except: pass
             
        msg_len_hist_labels = list(buckets_map.values())
        msg_len_hist_data = list(hist_data.values())

        stats = {
            "hourly_activity": hourly_counts,
            "hourly_labels": [f"{h}:00" for h in range(24)],
            "msglen_labels": list(buckets_map.values()),
            "msglen_data": list(hist_data.values()),
            "heatmap_data": heatmap_data,
            "heatmap_max": heatmap_max,
             "peak_analysis": {
                "peak_hour": peak_hour,
                "peak_day": peak_day,
                "peak_messages": peak_msgs,
                "quiet_period": quiet_period
            },
            "cumulative_msgs": [], # Deprecated or needs real calc
            "is_estimated": False 
        }
        
        # Save to cache
        await r.setex(cache_key, 60, json.dumps(stats))
        return stats
        
    finally:
        pass
    #     pass

async def get_summary_card_data(discord_dau=0, discord_mau=0, discord_wau=0, discord_users=0, guild_id: int = 615171377783242769):
    """
    Get summary card data using ONLY real data from Redis (Primary) and database (Fallback).
    Prioritizes live bot data for user counts.
    """
    r = await get_redis()
    
    real_total_users = discord_users
    real_msgs = 0
    
    try:
        # 1. Get real Discord message count
        total_msgs_str = await r.get(f"stats:total_msgs:{guild_id}")
        real_msgs = int(total_msgs_str) if total_msgs_str else 0
        
        # 2. Get real TOTAL members from bot presence (most accurate)
        bot_total_members = await r.get(f"presence:total:{guild_id}")
        if bot_total_members:
            real_total_users = int(bot_total_members)
            
    except Exception as e:
        print(f"Error fetching Redis stats: {e}")
    finally:
        pass
    #     pass
    
    return {
        "discord": {
            "users": real_total_users,
            "msgs": real_msgs,
            "dau": discord_dau,
            "mau": discord_mau,
            "wau": discord_wau
        },
        "generated_date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

def get_challenge_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists(): return {}
    try: return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except: return {}

def save_challenge_config(new_config: Dict[str, Any]):
    CONFIG_PATH.write_text(json.dumps(new_config, ensure_ascii=False, indent=2), encoding="utf-8")

async def get_realtime_online_count(guild_id: int = 615171377783242769) -> int:
    """
    Get REAL count of currently online members from Discord.
    Connects to bot data stored via bot presence updates.
    """
    # Try to get from Redis cache (bot updates this periodically)
    r = await get_redis()
    try:
        # Check if bot stores online count in Redis
        online_key = f"presence:online:{guild_id}"
        online_count = await r.get(online_key)
        if online_count:
            return int(online_count)
    except Exception:
        pass
    finally:
        pass
    #     pass
    
    # Fallback: return last DAU as approximation (not perfect but better than nothing)
    path = DATA_DIR / "active_users.json"
    if not path.exists(): return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data: return 0
        last_day = sorted(data.keys())[-1]
        val = data[last_day]
        return len(val) if isinstance(val, list) else 0
    except: return 0

async def save_user_guilds(user_id: str, guilds_data: List[Dict[str, Any]], expiry_seconds: int = 86400):
    """
    Save user guilds to Redis to avoid large session cookies.
    """
    r = await get_redis()
    try:
        key = f"session:guilds:{user_id}"
        await r.setex(key, expiry_seconds, json.dumps(guilds_data))
    except Exception as e:
        print(f"Error saving guilds to Redis: {e}")
    finally:
        pass
    #     pass


async def get_user_guilds(user_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve user guilds from Redis.
    """
    r = await get_redis()
    try:
        key = f"session:guilds:{user_id}"
        data = await r.get(key)
        if data is not None:
            return json.loads(data)
        return None # Cache miss
    except Exception as e:
        print(f"Error retrieving guilds from Redis: {e}")
        return []
    finally:
        pass
    #     pass
async def get_bot_guilds() -> List[str]:
    """Retrieve list of guild IDs where bot is present."""
    r = await get_redis()
    try:
        return list(await r.smembers("bot:guilds"))
    except Exception as e:
        print(f"Error fetching bot guilds: {e}")
        return []
    finally:
        pass
    #     pass

async def get_cached_roles(guild_id: int) -> List[Dict[str, str]]:
    """Retrieve roles from Redis cache or fallback to Discord API."""
    r = await get_redis()
    try:
        role_map = await r.hgetall(f"guild:roles:{guild_id}")
        if not role_map:
            # Fallback to API
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://discord.com/api/v10/guilds/{guild_id}/roles",
                    headers={"Authorization": f"Bot {BOT_TOKEN}"}
                )
                if resp.status_code == 200:
                    roles_data = resp.json()
                    for r_data in roles_data:
                        rid = r_data["id"]
                        rname = r_data["name"]
                        role_map[rid] = rname
                        await r.hset(f"guild:roles:{guild_id}", rid, rname)
        
        # Format for template
        return [{"id": k, "name": v} for k, v in sorted(role_map.items(), key=lambda x: x[1])]
    except Exception as e:
        print(f"Error fetching cached roles: {e}")
        return []
    finally:
        pass
    #     pass

async def get_trend_analysis(guild_id: int) -> Dict[str, Any]:
    """Calculate growth trends and predictions."""
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        # Get DAU for last 30 days
        now = datetime.now()
        dates_7d = [(now - timedelta(days=i)).strftime("%Y%m%d") for i in range(7)]
        dates_30d = [(now - timedelta(days=i)).strftime("%Y%m%d") for i in range(30)]
        
        dau_7d_keys = [f"hll:dau:{guild_id}:{d}" for d in dates_7d]
        dau_30d_keys = [f"hll:dau:{guild_id}:{d}" for d in dates_30d]
        
        dau_7d_vals = []
        for k in dau_7d_keys:
            dau_7d_vals.append(await r.pfcount(k))
            
        dau_30d_vals = []
        for k in dau_30d_keys:
            dau_30d_vals.append(await r.pfcount(k))
        
        # Calculate trends (simple linear regression slope or % change)
        # Using simple start vs end for now
        # Avoid division by zero
        start_7 = dau_7d_vals[-1] if dau_7d_vals else 0
        current_7 = dau_7d_vals[0] if dau_7d_vals else 0
        growth_7d = ((current_7 - start_7) / max(1, start_7)) * 100
        
        start_30 = dau_30d_vals[-1] if dau_30d_vals else 0
        current_30 = dau_30d_vals[0] if dau_30d_vals else 0
        growth_30d = ((current_30 - start_30) / max(1, start_30)) * 100
        
        avg_dau = sum(dau_30d_vals) / max(1, len(dau_30d_vals))
        
        # Simple prediction: avg growth + current
        prediction = int(avg_dau * (1 + (growth_30d / 100)))
        
        return {
            "growth_7d": round(growth_7d, 1),
            "growth_30d": round(growth_30d, 1),
            "avg_dau": int(avg_dau),
            "prediction": prediction
        }
    except Exception as e:
        print(f"Trend error: {e}")
        return {"growth_7d": 0, "growth_30d": 0, "avg_dau": 0, "prediction": 0}
    finally:
        pass

async def get_engagement_score(guild_id: int, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """Calculate engagement score based on messages, voice, and retention."""
    r = await get_redis_client()
    try:
        # Determine Date Range
        if start_date and end_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            except:
                start_dt = datetime.now() - timedelta(days=30)
                end_dt = datetime.now()
        else:
             start_dt = datetime.now() - timedelta(days=30)
             end_dt = datetime.now()
        
        days_diff = (end_dt - start_dt).days + 1
        if days_diff < 1: days_diff = 1
        
        # 1. Message Activity (Participation)
        tm_str = await r.get(f"stats:total_members:{guild_id}")
        total_members = int(tm_str) if tm_str else 100
        
        dau_sum = 0
        current_day = start_dt
        while current_day <= end_dt:
            d_str = current_day.strftime("%Y%m%d")
            dau_sum += await r.pfcount(f"hll:dau:{guild_id}:{d_str}")
            current_day += timedelta(days=1)
        
        avg_dau = dau_sum / days_diff
        
        # Normalize: Target 25% participation (aligned with security score)
        msg_participation_rate = (avg_dau / max(1, total_members))
        msg_score = min(100, (msg_participation_rate / 0.25) * 100)
        
        # 2. Voice Activity (Real - Range Limited)
        ts_start = start_dt.timestamp()
        ts_end = end_dt.replace(hour=23, minute=59, second=59).timestamp()
        
        total_voice_seconds = 0
        # Scan voice events (optimized scan)
        async for key in r.scan_iter(f"events:voice:{guild_id}:*"):
            events = await r.zrangebyscore(key, ts_start, ts_end)
            for evt_json in events:
                try:
                    data = json.loads(evt_json)
                    total_voice_seconds += data.get("duration", 0)
                except: pass
        
        # Norm: 30 mins per active user per day = 100 pts
        hours_per_dau = (total_voice_seconds / days_diff / 3600) / max(1, avg_dau)
        voice_score = min(100, (hours_per_dau / 0.5) * 100)
        
        # 3. Retention / Stickiness (DAU / MAU proxy)
        # For a custom range, "MAU" is "Total Unique Users in Range".
        # We can approximate this by merging HLLs for the range.
        keys = []
        curr = start_dt
        while curr <= end_dt:
             keys.append(f"hll:dau:{guild_id}:{curr.strftime('%Y%m%d')}")
             curr += timedelta(days=1)
        
        period_unique = 0
        if keys:
             # PFCOUNT supports multiple keys => result is cardinality of union
             # Filter logic to ensure keys exist to prevent redis errors if strict? 
             # Redis handles non-existent keys in PFCOUNT as empty HLLs usually.
             period_unique = await r.pfcount(*keys)
             
        # Stickiness = Avg Daily / Period Unique
        # If 10 users active total, and avg daily is 5 => 50% Stickiness.
        stickiness = (avg_dau / max(1, period_unique)) if period_unique > 0 else 0
        
        # Target: 30% Stickiness (Good for communities)
        retention_score = min(100, (stickiness / 0.30) * 100)
        
        overall_score = int((msg_score * 0.4) + (voice_score * 0.3) + (retention_score * 0.3))
        
        return {
            "score": overall_score,
            "msg_activity": int(msg_score),
            "voice_activity": int(voice_score),
            "retention": int(retention_score),
            "debug_avg_dau": avg_dau,
            "debug_voice_hours": total_voice_seconds / 3600,
            "debug_unique": period_unique
        }
    except Exception as e:
         print(f"Engagement error: {e}")
         return {"score": 0, "msg_activity": 0, "voice_activity": 0, "retention": 0}
    finally:
        pass

def generate_security_insights(metrics: Dict[str, Any]):
    """
    Generate a comprehensive list of actionable insights based on calculated metrics.
    Returns structured insights with categories and priority levels.
    Priority: critical (🚨), warning (⚠️), info (ℹ️), success (✅)
    """
    insights = []
    
    # Extract all metrics
    mod_ratio = metrics.get("mod_ratio", 100)
    users_per_mod = metrics.get("users_per_mod", 100)
    mod_actions = metrics.get("mod_actions", 0)
    ver_level = metrics.get("verification_level", 0)
    mfa_level = metrics.get("mfa_level", 0)
    explicit_filter = metrics.get("explicit_filter", 1)
    participation_rate = metrics.get("participation_rate", 0)
    reply_ratio = metrics.get("reply_ratio", 0)
    voice_hours = metrics.get("voice_hours_per_dau", 0)
    churn_rate = metrics.get("churn_rate", 0)
    stickiness = metrics.get("stickiness", 0)
    overall_score = metrics.get("overall_score", 0)
    total_members = metrics.get("total_members", 0)
    avg_dau = metrics.get("avg_dau", 0)
    growth_rate = metrics.get("growth_rate", 0)
    engagement_score = metrics.get("engagement_score", 50)
    avg_msg_length = metrics.get("avg_msg_length", 0)
    weekend_ratio = metrics.get("weekend_ratio", 1.0)
    new_member_retention = metrics.get("new_member_retention", 100)
    
    def add(priority: str, category: str, title: str, detail: str):
        """Helper to add structured insight"""
        icon_map = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️", "success": "✅", "tip": "💡"}
        icon = icon_map.get(priority, "📊")
        insights.append({
            "priority": priority,
            "category": category,
            "text": f"{icon} **{title}**: {detail}"
        })
    
    # ══════════════════════════════════════════════════════════════════════════
    # 1. TÝM & MODERACE (👥)
    # ══════════════════════════════════════════════════════════════════════════
    
    if mod_ratio < 40:
        add("critical", "team", "Kritický stav", f"{users_per_mod:.0f} členů na moderátora! Urgentně naberte.")
    elif mod_ratio < 60:
        add("warning", "team", "Nedostatek moderátorů", f"{users_per_mod:.0f} uživatelů na mod je nad limitem.")
    elif mod_ratio < 80:
        add("info", "team", "Vytížení týmu", "Poměr je hraniční – mějte záložní členy.")
    elif mod_ratio >= 95 and users_per_mod < 30:
        add("success", "team", "Silný tým", "Skvělý poměr moderátorů – rychlá reakce zaručena.")
    
    if mod_actions == 0:
        add("warning", "team", "Žádná moderace", "Za měsíc 0 akcí. Ověřte logging bota.")
    elif mod_actions < 3:
        add("info", "team", "Klidná komunita", "Minimální zásahy – komunita je ukázněná.")
    elif mod_actions > 100 and mod_actions <= 300:
        add("info", "team", "Aktivní moderace", f"{mod_actions} akcí/měsíc. Tým je bdělý.")
    elif mod_actions > 300 and mod_actions <= 500:
        add("warning", "team", "Vysoká zátěž", f"{mod_actions} akcí. Zvažte rotaci moderátorů.")
    elif mod_actions > 500:
        add("critical", "team", "Přetížení", f"{mod_actions} akcí! Možný systémový problém.")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 2. ZABEZPEČENÍ (🛡️)
    # ══════════════════════════════════════════════════════════════════════════
    
    if ver_level == 0:
        add("critical", "security", "Bez ověření", "Kdokoli může psát ihned po vstupu!")
    elif ver_level == 1:
        add("warning", "security", "Slabé ověření", "Pouze e-mail. Zvažte vyšší úroveň.")
    elif ver_level >= 3:
        add("success", "security", "Silné ověření", f"Úroveň {ver_level}/4 – dobrá ochrana.")
    
    if mfa_level == 0:
        add("warning", "security", "Chybí 2FA", "Moderátoři nemají povinné 2FA.")
    else:
        add("success", "security", "2FA aktivní", "Moderátoři mají povinné 2FA.")
    
    if explicit_filter == 0:
        add("warning", "security", "Žádný filtr", "Explicitní obsah není skenován.")
    elif explicit_filter == 1:
        add("info", "security", "Částečný filtr", "Skenování jen u členů bez role.")
    elif explicit_filter == 2:
        add("success", "security", "Plný filtr", "Veškerý obsah je skenován.")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 3. AKTIVITA & ZAPOJENÍ (📈)
    # ══════════════════════════════════════════════════════════════════════════
    
    if participation_rate < 1:
        add("critical", "activity", "Mrtvý server", "Pod 1% aktivních. Potřeba reaktivace.")
    elif participation_rate < 5:
        add("warning", "activity", "Velmi nízká aktivita", f"Pouze {participation_rate:.1f}% denně aktivních.")
    elif participation_rate < 10:
        add("info", "activity", "Nízké zapojení", f"{participation_rate:.1f}% aktivních. Zkuste eventy.")
    elif participation_rate < 20:
        add("info", "activity", "Průměrná aktivita", f"{participation_rate:.1f}% denní účast.")
    elif participation_rate >= 30:
        add("success", "activity", "Vysoké zapojení", f"{participation_rate:.1f}% aktivních – výborné!")
    
    if reply_ratio < 5:
        add("info", "activity", "Oznámkový styl", "Téměř žádné odpovědi – server je broadcast.")
    elif reply_ratio < 15:
        add("info", "activity", "Málo konverzací", f"{reply_ratio:.0f}% odpovědí. Zkuste ankety.")
    elif reply_ratio >= 40:
        add("success", "activity", "Živá diskuze", f"{reply_ratio:.0f}% zpráv jsou odpovědi!")
    
    if voice_hours < 0.05:
        add("info", "activity", "Prázdné voice", "Téměř nulová hlasová aktivita.")
    elif voice_hours < 0.1:
        add("info", "activity", "Tiché kanály", "Minimální voice. Zkuste events.")
    elif voice_hours >= 0.5:
        add("success", "activity", "Aktivní voice", f"Průměrně {voice_hours:.1f}h/den na uživatele.")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 4. RETENCE & ODCHODY (📉)
    # ══════════════════════════════════════════════════════════════════════════
    
    if churn_rate > 50:
        add("critical", "retention", "Masový exodus", f"{churn_rate:.0f}% odchodů! Kritické.")
    elif churn_rate > 30:
        add("critical", "retention", "Vysoký odliv", f"{churn_rate:.1f}% opouští. Prověřte příčiny.")
    elif churn_rate > 15:
        add("warning", "retention", "Zvýšený churn", f"{churn_rate:.1f}% odchodů. Zlepšete onboarding.")
    elif churn_rate > 5:
        add("info", "retention", "Normální fluktuace", f"{churn_rate:.1f}% – běžné rozmezí.")
    elif churn_rate <= 2:
        add("success", "retention", "Excelentní retence", "Minimální odchody – členové zůstávají!")
    
    if stickiness < 5:
        add("warning", "retention", "Nízká stickiness", "DAU/MAU pod 5%. Vrací se zřídka.")
    elif stickiness < 15:
        add("info", "retention", "Příležitostní návštěvy", f"Stickiness {stickiness:.0f}% – hobby komunita.")
    elif stickiness < 30:
        add("info", "retention", "Dobrá stickiness", f"{stickiness:.0f}% DAU/MAU – solidní.")
    elif stickiness >= 40:
        add("success", "retention", "Návyková komunita", f"Stickiness {stickiness:.0f}%! Denně se vrací.")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 5. RŮST (🌱)
    # ══════════════════════════════════════════════════════════════════════════
    
    if growth_rate < -10:
        add("critical", "growth", "Úbytek členů", f"{growth_rate:.1f}% – server ztrácí lidi.")
    elif growth_rate < 0:
        add("warning", "growth", "Stagnace", f"{growth_rate:.1f}% – mírný pokles.")
    elif growth_rate > 0 and growth_rate < 5:
        add("info", "growth", "Pomalý růst", f"+{growth_rate:.1f}% – stabilní.")
    elif growth_rate >= 5 and growth_rate < 15:
        add("success", "growth", "Zdravý růst", f"+{growth_rate:.1f}% měsíčně.")
    elif growth_rate >= 15:
        add("success", "growth", "Virální růst", f"+{growth_rate:.1f}%! Moderace stíhá?")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 6. KOMUNITA (🏠)
    # ══════════════════════════════════════════════════════════════════════════
    
    if avg_msg_length > 0 and avg_msg_length < 20:
        add("info", "community", "Krátké zprávy", f"Průměr {avg_msg_length:.0f} znaků – chat styl.")
    elif avg_msg_length >= 100:
        add("success", "community", "Obsahové diskuze", f"Průměr {avg_msg_length:.0f} znaků – kvalita!")
    
    if weekend_ratio > 1.5:
        add("info", "community", "Víkendová komunita", "1.5x vyšší aktivita o víkendech.")
    elif weekend_ratio < 0.5:
        add("info", "community", "Pracovní komunita", "Aktivnější během týdne.")
    
    if new_member_retention < 30:
        add("warning", "community", "Únik nováčků", "Pod 30% zůstává. Vylepšete onboarding.")
    elif new_member_retention >= 70:
        add("success", "community", "Vítající komunita", f"{new_member_retention:.0f}% nováčků zůstává!")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 7. TIPY & DOPORUČENÍ (💡)
    # ══════════════════════════════════════════════════════════════════════════
    
    if total_members > 100 and participation_rate < 10 and voice_hours < 0.1:
        add("tip", "tips", "Event tip", "Zkuste voice event nebo AMA session pro oživení.")
    
    if reply_ratio < 20 and participation_rate > 5:
        add("tip", "tips", "Interakce tip", "Přidejte ankety/hlasování pro více konverzací.")
    
    if churn_rate > 10 and new_member_retention < 50:
        add("tip", "tips", "Onboarding tip", "Vytvořte uvítací kanál s pravidly a FAQ.")
    
    if mod_actions > 200 and mod_ratio < 70:
        add("tip", "tips", "Automatizace tip", "Zvažte AutoMod pro odlehčení týmu.")
    
    # ══════════════════════════════════════════════════════════════════════════
    # 8. OCENĚNÍ (🏆)
    # ══════════════════════════════════════════════════════════════════════════
    
    achievements = 0
    if overall_score >= 80: achievements += 1
    if participation_rate >= 20: achievements += 1
    if churn_rate <= 5: achievements += 1
    if mod_ratio >= 90: achievements += 1
    if stickiness >= 30: achievements += 1
    if growth_rate >= 5: achievements += 1
    
    if achievements >= 4:
        add("success", "achievement", "Vzorová komunita", f"Vynikáte v {achievements} oblastech! 🏆")
    elif achievements >= 2:
        add("success", "achievement", "Na dobré cestě", f"Silní ve {achievements} oblastech.")
    
    # ══════════════════════════════════════════════════════════════════════════
    # FALLBACK
    # ══════════════════════════════════════════════════════════════════════════
    
    if not insights:
        if overall_score >= 90:
            add("success", "general", "Perfektní kondice", "Všechny metriky jsou ukázkové!")
        elif overall_score >= 70:
            add("success", "general", "Stabilní stav", "Vše v normě. Skvělá práce!")
        else:
            add("info", "general", "Standardní úroveň", "Server funguje – prostor pro růst.")
    
    # Sort by priority (critical first, then warning, info, success, tip)
    priority_order = {"critical": 0, "warning": 1, "info": 2, "tip": 3, "success": 4}
    insights.sort(key=lambda x: priority_order.get(x["priority"], 5))
    
    # Return just the text for backward compatibility, but structured
    return [i["text"] for i in insights]


async def get_security_score(guild_id: int, days: int = 7) -> Dict[str, Any]:
    """
    Calculate security score based on multiple factors:
    - Moderator ratio (users per mod)
    - Server security settings (verification level, etc.)
    - User engagement/comfort (DAU, Reply Ratio, Voice - Last X Days)
    - Moderation health (active moderation)
    """
    r = await get_redis()
    try:
        # ========== LOAD CONFIGURABLE SETTINGS ==========
        # Weights
        weights = {"mod_ratio": 25, "security": 25, "engagement": 25, "moderation": 25}
        stored_weights = await r.hgetall("config:security_weights")
        if stored_weights:
            for k, v in stored_weights.items():
                weights[k] = int(v)
        
        # Ideals
        ideals = {
            "mod_ratio_min": 50, "mod_ratio_max": 100,
            "dau_percent": 25, # UPDATED: 25% target
            "mod_actions_min": 1, "mod_actions_max": 5,
            "verification_level": 2
        }
        stored_ideals = await r.hgetall("config:security_ideals")
        if stored_ideals:
            for k, v in stored_ideals.items():
                ideals[k] = float(v) if '.' in str(v) else int(v)
        
        # ========== 1. MODERATOR RATIO SCORE ==========
        total_members_str = await r.get(f"presence:total:{guild_id}")
        if not total_members_str:
            total_members_str = await r.get(f"stats:total_members:{guild_id}")
        total_members = int(total_members_str) if total_members_str else 100
        
        mod_count_str = await r.get(f"stats:mod_count:{guild_id}")
        mod_count = int(mod_count_str) if mod_count_str else max(1, total_members // 100)
        
        users_per_mod = total_members / max(1, mod_count)
        ideal_min, ideal_max = ideals["mod_ratio_min"], ideals["mod_ratio_max"]
        
        if ideal_min <= users_per_mod <= ideal_max:
            mod_ratio_score = 100
        elif users_per_mod < ideal_min:
            mod_ratio_score = max(60, 100 - ((ideal_min - users_per_mod) / ideal_min) * 40)
        else:
            over_ratio = (users_per_mod - ideal_max) / ideal_max
            mod_ratio_score = max(0, 100 - over_ratio * 100)
        
        # ========== 2. SERVER SECURITY SETTINGS SCORE ==========
        verification_level = int(await r.get(f"guild:verification_level:{guild_id}") or 2)
        verification_score = min(60, (verification_level / max(1, ideals["verification_level"])) * 60)
        explicit_score = (int(await r.get(f"guild:explicit_filter:{guild_id}") or 1) / 2) * 20
        mfa_score = 20 if int(await r.get(f"guild:mfa_level:{guild_id}") or 0) else 0
        
        security_settings_score = min(100, verification_score + explicit_score + mfa_score)
        
        # ========== 3. USER ENGAGEMENT SCORE (LAST X DAYS) ==========
        now = datetime.now()
        start_ts = (now - timedelta(days=days)).timestamp()
        
        # 3a. Avg DAU (Last X Days)
        dau_sum = 0
        for i in range(days):
            d_str = (now - timedelta(days=i)).strftime("%Y%m%d")
            dau_sum += await r.pfcount(f"hll:dau:{guild_id}:{d_str}")
        avg_dau = dau_sum / days
        
        participation_rate = (avg_dau / max(1, total_members)) * 100
        participation_score = min(40, (participation_rate / ideals["dau_percent"]) * 40)
        
        # 3b. Reply Ratio & Voice (Last X Days from EVENTS)
        # We need to scan event keys. This might be heavy for large servers, 
        # but for <10k members it's okay.
        
        # Scan Message Events
        total_msgs = 0
        total_replies = 0
        async for key in r.scan_iter(f"events:msg:{guild_id}:*"):
            # key: events:msg:{gid}:{uid} (ZSET)
            # Fetch range by score (timestamp)
            events = await r.zrangebyscore(key, start_ts, "+inf")
            for evt_json in events:
                try:
                    data = json.loads(evt_json)
                    total_msgs += 1
                    if data.get("reply"): total_replies += 1
                except: pass
        
        measured_reply_ratio = (total_replies / max(1, total_msgs)) * 100
        reply_score = min(30, (measured_reply_ratio / 20) * 30) # Target ~20% replies
        
        # Scan Voice Events
        total_voice_seconds = 0
        async for key in r.scan_iter(f"events:voice:{guild_id}:*"):
            events = await r.zrangebyscore(key, start_ts, "+inf")
            for evt_json in events:
                try:
                    data = json.loads(evt_json)
                    total_voice_seconds += data.get("duration", 0)
                except: pass
                
        # Target: 10 mins per active user per day?
        # daily_voice_per_user = (total_voice_seconds / days) / max(1, avg_dau)
        # Let's say target is 30 mins (1800s) = 30 pts
        hours_per_dau = (total_voice_seconds / days / 3600) / max(1, avg_dau)
        # Target: 0.5 hours/day/user
        voice_score = min(30, (hours_per_dau / 0.5) * 30)

        engagement_score = int(participation_score + reply_score + voice_score)
        
        # ========== 4. MODERATION HEALTH SCORE ==========
        # Using 30d stat is fine for health check
        mod_actions = int(await r.get(f"stats:mod_actions_30d:{guild_id}") or (total_members // 50))
        
        actions_per_100_users = (mod_actions / max(1, total_members)) * 100
        ideal_actions_min = ideals["mod_actions_min"]
        ideal_actions_max = ideals["mod_actions_max"]
        
        if ideal_actions_min <= actions_per_100_users <= ideal_actions_max:
            moderation_score = 100
        elif actions_per_100_users < ideal_actions_min:
            # Very few actions - neutral
            moderation_score = 50
        elif actions_per_100_users <= ideal_actions_max * 2:
            # Active moderation - still acceptable
            moderation_score = 80
        else:
            # Very high - server might have problems
            moderation_score = max(20, 80 - (actions_per_100_users - ideal_actions_max * 2) * 5)
        
        # ========== CALCULATE OVERALL SCORE ==========
        overall_score = int(
            (mod_ratio_score * weights["mod_ratio"] / 100) +
            (security_settings_score * weights["security"] / 100) +
            (engagement_score * weights["engagement"] / 100) +
            (moderation_score * weights["moderation"] / 100)
        )
        
        # Determine rating text
        if overall_score >= 80:
            rating = "Vynikající"
            rating_color = "#10B981"
        elif overall_score >= 60:
            rating = "Dobrý"
            rating_color = "#3B82F6"
        elif overall_score >= 40:
            rating = "Průměrný"
            rating_color = "#F59E0B"
        else:
            rating = "Nízký"
            rating_color = "#EF4444"

        # ========== 5. ADDITIONAL METRICS FOR INSIGHTS ==========

        # Churn Rate (Approx from current month)
        curr_month = now.strftime("%Y-%m")
        month_leaves = int(await r.hget(f"stats:leaves:{guild_id}", curr_month) or 0)
        month_joins = int(await r.hget(f"stats:joins:{guild_id}", curr_month) or 0)
        churn_rate = (month_leaves / max(1, total_members)) * 100
        
        # Growth Rate (net growth as % of total)
        net_growth = month_joins - month_leaves
        growth_rate = (net_growth / max(1, total_members)) * 100
        
        # Stickiness (DAU/MAU)
        mau_keys = [f"hll:dau:{guild_id}:{(now - timedelta(days=j)).strftime('%Y%m%d')}" for j in range(30)]
        mau = await r.pfcount(*mau_keys)
        stickiness = (avg_dau / max(1, mau)) * 100 if mau > 0 else 0

        explicit_filter = int(await r.get(f"guild:explicit_filter:{guild_id}") or 1)
        mfa_level = int(await r.get(f"guild:mfa_level:{guild_id}") or 0)
        
        # Average message length (from deep stats if available)
        avg_msg_length = 0
        try:
            msg_len_data = await r.get(f"stats:avg_msg_length:{guild_id}")
            avg_msg_length = float(msg_len_data) if msg_len_data else 0
        except:
            pass
        
        # Weekend vs Weekday ratio
        weekend_ratio = 1.0
        try:
            weekend_msgs = 0
            weekday_msgs = 0
            for i in range(14):  # Last 2 weeks
                d = now - timedelta(days=i)
                d_str = d.strftime("%Y%m%d")
                h_data = await r.hgetall(f"stats:hourly:{guild_id}:{d_str}")
                day_sum = sum(int(float(v)) for v in h_data.values()) if h_data else 0
                if d.weekday() >= 5:  # Weekend
                    weekend_msgs += day_sum
                else:
                    weekday_msgs += day_sum
            # Normalize per day (4 weekend days, 10 weekday days in 2 weeks)
            weekend_avg = weekend_msgs / 4 if weekend_msgs else 1
            weekday_avg = weekday_msgs / 10 if weekday_msgs else 1
            weekend_ratio = weekend_avg / max(1, weekday_avg)
        except:
            pass

        metrics = {
            "overall_score": overall_score,
            "mod_ratio": mod_ratio_score,
            "users_per_mod": users_per_mod,
            "mod_actions": mod_actions,
            "verification_level": verification_level,
            "mfa_level": mfa_level,
            "explicit_filter": explicit_filter,
            "participation_rate": participation_rate,
            "reply_ratio": measured_reply_ratio,
            "voice_hours_per_dau": hours_per_dau,
            "churn_rate": churn_rate,
            "stickiness": stickiness,
            # New metrics for expanded insights
            "total_members": total_members,
            "avg_dau": avg_dau,
            "growth_rate": growth_rate,
            "engagement_score": engagement_score,
            "avg_msg_length": avg_msg_length,
            "weekend_ratio": weekend_ratio
        }

        # ========== JSON RETURN ==========
        return {
            "overall_score": overall_score,
            "rating": rating,
            "rating_color": rating_color,
            "weights": weights,
            "components": {
                "mod_ratio": {
                    "score": int(mod_ratio_score),
                    "weight": int(weights["mod_ratio"]),
                    "label": "Poměr moderátorů",
                    "detail": f"{users_per_mod:.0f} uživatelů/mod"
                },
                "security": {
                    "score": int(security_settings_score),
                    "weight": int(weights["security"]),
                    "label": "Zabezpečení serveru",
                    "detail": f"Úroveň {verification_level}/4"
                },
                "engagement": {
                    "score": int(engagement_score),
                    "weight": int(weights["engagement"]),
                    "label": "Zapojení uživatelů",
                    "detail": f"{participation_rate:.2f}% aktivních" if participation_rate < 1 else f"{participation_rate:.1f}% aktivních"
                },
                "moderation": {
                    "score": int(moderation_score),
                    "weight": int(weights["moderation"]),
                    "label": "Zdraví moderace",
                    "detail": f"{mod_actions} akcí/měsíc"
                }
            },
            "insights": generate_security_insights(metrics)
        }
    except Exception as e:
        print(f"Security score error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "overall_score": 0,
            "rating": "Neznámý",
            "rating_color": "#6B7280",
            "components": {},
            "insights": ["Nepodařilo se načíst postřehy."]
        }
    finally:
        pass



async def get_insights(guild_id: int) -> List[Dict[str, str]]:
    """Generate smart insights based on stats."""
    insights = []
    
    try:
        trends = await get_trend_analysis(guild_id)
        score = await get_engagement_score(guild_id)
        
        # Growth
        if trends["growth_7d"] > 5:
            insights.append({"type": "positive", "text": "🚀 Silný týdenní růst! Počet aktivních uživatelů stoupá."})
        elif trends["growth_7d"] < -5:
            insights.append({"type": "negative", "text": "📉 Pozor, týdenní aktivita klesá. Zkuste uspořádat event."})
            
        # Retention
        if score["retention"] > 60:
            insights.append({"type": "positive", "text": "💎 Vysoká retence! Uživatelé se rádi vrací."})
        elif score["retention"] < 20:
             insights.append({"type": "negative", "text": "⚠️ Nízká retence. Zaměřte se na udržení nových členů."})

        # Voice
        if score["voice_activity"] > 50:
            insights.append({"type": "positive", "text": "🗣️ Komunita je velmi upovídaná v hlasových kanálech!"})
        elif score["voice_activity"] < 10 and score["msg_activity"] > 50:
            insights.append({"type": "neutral", "text": "💬 Lidé píší, ale málo mluví. Zkuste vytvořit 'Chill' voice room."})
            
        # Commands
        cmd_stats = await get_command_stats(guild_id, limit=1)
        if cmd_stats:
            top_cmd = cmd_stats[0]
            insights.append({"type": "neutral", "text": f"🤖 Nejoblíbenější příkaz je '/{top_cmd['name']}' ({top_cmd['count']}x)."})

        # Traffic
        traffic = await load_member_stats(guild_id)
        # Sum last ~30 days (1 month usually)
        if traffic and "joins" in traffic and traffic["joins"]:
             last_month_joins = traffic["joins"][-1] if len(traffic["joins"]) > 0 else 0
             last_month_leaves = traffic["leaves"][-1] if len(traffic["leaves"]) > 0 else 0
             if last_month_joins > last_month_leaves * 2:
                 insights.append({"type": "positive", "text": "📈 Skvělý nábor! Přichází 2x více lidí než odchází."})

        # Prediction
        if trends["prediction"] > trends["avg_dau"] * 1.1:
             insights.append({"type": "neutral", "text": f"🔮 Očekáváme růst na cca {trends['prediction']} denních uživatelů."})
             
        # Default if empty
        if not insights:
            insights.append({"type": "neutral", "text": "Zatím nemám dost dat pro generování specifických postřehů."})
            
    except Exception as e:
         print(f"Insights error: {e}")
         insights.append({"type": "error", "text": "Chyba při generování postřehů."})
         
    return insights

async def get_time_comparisons(guild_id: int, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """Calculate WoW and MoM DAU changes relative to end_date."""
    # We want 60 days back from end_date
    if end_date:
        e_dt = datetime.strptime(end_date, "%Y-%m-%d")
    else:
        e_dt = datetime.now()
    
    # Fetch 60 days
    activity_stats = await get_activity_stats(guild_id, end_date=e_dt.strftime("%Y-%m-%d"), days=60)
    dau_data = activity_stats.get("dau_data", [])
    
    # WoW
    if len(dau_data) >= 14:
        this_week = sum(dau_data[-7:]) / 7
        last_week = sum(dau_data[-14:-7]) / 7
        wow_change = ((this_week - last_week) / max(1, last_week)) * 100
    else:
        # Fallback for insufficient data
        this_week = sum(dau_data) / len(dau_data) if dau_data else 0
        last_week = 0
        wow_change = 0 
        
    # MoM
    if len(dau_data) >= 60:
        this_month = sum(dau_data[-30:]) / 30
        last_month = sum(dau_data[-60:-30]) / 30
        mom_change = ((this_month - last_month) / max(1, last_month)) * 100
    else:
        # Fallback for insufficient data
        this_month = sum(dau_data) / len(dau_data) if dau_data else 0
        last_month = 0
        mom_change = 0
        
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

async def get_voice_leaderboard(guild_id: int, limit: int = 10, start_date: str = None, end_date: str = None, role_id: str = "all") -> List[Dict[str, Any]]:
    """Fetch top users by voice duration - currently all-time fallback."""
    # TODO: Implement date-stamped voice keys if tracked daily
    r = await get_redis()
    try:
        data = await r.zrevrange(f"stats:voice_duration:{guild_id}", 0, limit - 1, withscores=True)
        return [{"user_id": uid, "duration_seconds": int(score)} for uid, score in data]
    except Exception as e:
        print(f"Voice stats error: {e}")
        return []

async def get_command_stats(guild_id: int, limit: int = 10, start_date: str = None, end_date: str = None, role_id: str = "all") -> List[Dict[str, Any]]:
    """Fetch top used commands."""
    r = await get_redis()
    try:
        data = await r.hgetall(f"stats:commands:{guild_id}")
        sorted_data = sorted(data.items(), key=lambda item: int(item[1]), reverse=True)[:limit]
        return [{"name": k, "count": int(v)} for k, v in sorted_data]
    except Exception as e:
        print(f"Command stats error: {e}")
        return []

async def get_traffic_stats(guild_id: int, days: int = 30, start_date: str = None, end_date: str = None, role_id: str = "all") -> Dict[str, Any]:
    """Fetch Joins vs Leaves for traffic chart."""
    return await load_member_stats(guild_id, start_date=start_date, end_date=end_date) 

async def get_leaderboard_data(guild_id: int, limit: int = 15, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """Fetch user leaderboard with optional date filtering."""
    r = await get_redis()
    try:
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            
            # If range is huge (> 365 days), use all-time as fallback
            if (end_dt - start_dt).days > 365:
                top_users = await r.zrevrange(f"leaderboard:messages:{guild_id}", 0, limit - 1, withscores=True)
            else:
                # Aggregate daily ZSETs
                daily_keys = []
                curr = start_dt
                while curr <= end_dt:
                    daily_keys.append(f"stats:user_daily:{guild_id}:{curr.strftime('%Y%m%d')}")
                    curr += timedelta(days=1)
                
                # Filter only existing keys
                existing_keys = []
                for k in daily_keys:
                    if await r.exists(k): existing_keys.append(k)
                
                if not existing_keys:
                    # If no daily data, maybe it's all-time or just empty
                    top_users = await r.zrevrange(f"leaderboard:messages:{guild_id}", 0, limit - 1, withscores=True)
                else:
                    temp_key = f"tmp:leaderboard:{guild_id}:{start_date}:{end_date}"
                    await r.zunionstore(temp_key, existing_keys)
                    await r.expire(temp_key, 60)
                    top_users = await r.zrevrange(temp_key, 0, limit - 1, withscores=True)
        else:
            top_users = await r.zrevrange(f"leaderboard:messages:{guild_id}", 0, limit - 1, withscores=True)

        leaderboard = []
        for user_id_str, msg_count in top_users:
            uid = int(float(user_id_str))
            name = await r.hget(f"user:info:{uid}", "name")
            if not name: name = f"User {uid}"
            
            lengths = await r.lrange(f"leaderboard:msg_lengths:{guild_id}:{uid}", 0, -1)
            avg_len = sum(int(l) for l in lengths) / len(lengths) if lengths else 0
            
            leaderboard.append({
                "user_id": uid, "name": name,
                "total_messages": int(msg_count),
                "avg_message_length": round(avg_len, 1)
            })
        return {"leaderboard": leaderboard}
    except Exception as e:
        print(f"Leaderboard data error: {e}")
        return {"leaderboard": [], "error": str(e)}

async def get_channel_distribution(guild_id: int, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
    """Fetch message distribution by channel, optionally filtered by date."""
    r = await get_redis()
    try:
        if not start_date or not end_date:
            data = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, 14, withscores=True)
            return [{"channel_id": cid, "count": int(score)} for cid, score in data]

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date != datetime.now().strftime("%Y-%m-%d") else datetime.now()
        
        # If range is huge (> 365 days), use all-time as fallback/baseline
        if (end_dt - start_dt).days > 365:
            data = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, 14, withscores=True)
            return [{"channel_id": cid, "count": int(score)} for cid, score in data]

        all_channels = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, -1)
        if not all_channels: return []

        pipe = r.pipeline()
        curr, day_count = end_dt, 0
        while curr >= start_dt:
            d_str = curr.strftime("%Y%m%d")
            for cid in all_channels:
                cid_str = cid
                pipe.get(f"stats:channel:{guild_id}:{cid_str}:{d_str}")
            curr -= timedelta(days=1)
            day_count += 1
            if day_count > 365: break # Cap for performance

        responses = await pipe.execute()
        channel_counts = Counter()
        num_channels = len(all_channels)
        
        # Process responses
        for d_idx in range(day_count):
            for c_idx in range(num_channels):
                val = responses[d_idx * num_channels + c_idx]
                if val is not None:
                    cid_str = all_channels[c_idx] 
                    try:
                        channel_counts[cid_str] += int(float(val))
                    except (ValueError, TypeError):
                        pass
        
        if not channel_counts:
            # Fallback to all-time if no daily data found for range
            data = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, 14, withscores=True)
            return [{"channel_id": cid, "count": int(score)} for cid, score in data]
            
        return [{"channel_id": cid, "count": count} for cid, count in channel_counts.most_common(15)]
    except Exception as e:
        print(f"Channel dist error: {e}")
        return []

async def get_dashboard_team(guild_id: int) -> List[Dict[str, Any]]:
    """
    Get all users with explicit dashboard access for a guild.
    """
    r = await get_redis()
    try:
        # Get set of user IDs
        user_ids = await r.smembers(f"dashboard:team:{guild_id}")
        team = []
        
        for uid in user_ids:
            perms = await r.smembers(f"dashboard:perms:{guild_id}:{uid}")
            # Try to get user info if cached
            user_info = await r.hgetall(f"user:info:{uid}") or {}
            
            team.append({
                "id": uid,
                "username": user_info.get("username", "Unknown User"),
                "avatar": user_info.get("avatar"),
                "permissions": list(perms)
            })
            
        return team
    except Exception as e:
        print(f"Error fetching dashboard team: {e}")
        return []
    finally:
        pass

async def get_dashboard_permissions(guild_id: int, user_id: str, discord_role: str = "guest") -> List[str]:
    """
    Get effective permissions for a user on a guild.
    """
    # 1. Global Admin always has access
    # (assuming we check global admin before calling this or inside)
    if discord_role == "admin": 
        return ["*"]

    # 2. Check guild-specific access source
    from .utils import get_user_guilds
    user_guilds = await get_user_guilds(user_id)
    
    guild_info = next((g for g in user_guilds if str(g["id"]) == str(guild_id)), None)
    
    if not guild_info:
        # User has no access to this guild at all
        return []

    # 3. Check for Super Admin Access
    # Only Discord Administrators (0x8) get automatic full access.
    # Discord Moderators (0x20) are treated as guests unless added to Team.
    if guild_info.get("is_admin"):
        return ["*"]

    # 4. Check Redis Permissions (Team Access)
    r = await get_redis()
    try:
        perms = await r.smembers(f"dashboard:perms:{guild_id}:{user_id}")
        return list(perms) if perms else []
    except:
        return []

async def add_dashboard_user(guild_id: int, user_id: str, user_data: Dict[str, str], permissions: List[str]):
    """
    Add a user to the dashboard team.
    """
    r = await get_redis()
    try:
        # Add to team set
        await r.sadd(f"dashboard:team:{guild_id}", user_id)
        
        # Save permissions (replace existing)
        perm_key = f"dashboard:perms:{guild_id}:{user_id}"
        await r.delete(perm_key)
        if permissions:
            await r.sadd(perm_key, *permissions)
            
        # Cache basic user info
        if user_data:
             await r.hset(f"user:info:{user_id}", mapping=user_data)
             
        return True
    except Exception as e:
        print(f"Error adding dashboard user: {e}")
        return False
    finally:
        pass

async def remove_dashboard_user(guild_id: int, user_id: str):
    """
    Remove a user from the dashboard team.
    """
    r = await get_redis()
    try:
        await r.srem(f"dashboard:team:{guild_id}", user_id)
        await r.delete(f"dashboard:perms:{guild_id}:{user_id}")
        return True
    except Exception as e:
        print(f"Error removing dashboard user: {e}")
        return False
    finally:
        pass
