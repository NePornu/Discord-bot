import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict, Counter
import redis.asyncio as redis

DATA_DIR = Path("data")
CONFIG_PATH = DATA_DIR / "challenge_config.json"

def load_member_stats() -> Dict[str, Any]:
    """
    Načte data z member_counts.json a vrátí struktury pro:
    - Historii celkového počtu (Line Chart)
    - Tok členů Joins/Leaves (Stacked Bar Chart)
    """
    path = DATA_DIR / "member_counts.json"
    if not path.exists():
        return {"labels": [], "total": [], "joins": [], "leaves": []}
    
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        sorted_keys = sorted(data.keys())
        
        cumulative_count = 0
        total_counts = []
        joins = []
        leaves = []
        
        for k in sorted_keys:
            month_data = data[k]
            if isinstance(month_data, dict):
                j = month_data.get("joins", 0)
                l = month_data.get("leaves", 0)
                net = j - l
                cumulative_count += net
                total_counts.append(cumulative_count)
                joins.append(j)
                leaves.append(l)
            else:
                try:
                    c = int(month_data)
                    cumulative_count = c
                    total_counts.append(c)
                    joins.append(0)
                    leaves.append(0)
                except:
                    total_counts.append(cumulative_count)
                    joins.append(0)
                    leaves.append(0)

        return {
            "labels": sorted_keys,
            "total": total_counts,
            "joins": joins,
            "leaves": leaves
        }
    except Exception as e:
        print(f"Error loading member_counts: {e}")
        return {"labels": [], "total": [], "joins": [], "leaves": []}

def get_activity_stats() -> Dict[str, Any]:
    """
    Základní aktivita: DAU, MAU, Avg DAU.
    """
    path = DATA_DIR / "active_users.json"
    if not path.exists():
        return {"dau_labels": [], "dau_data": [], "mau_labels": [], "mau_data": [], "avg_dau": 0, "raw_data": {}}

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        sorted_days = sorted(raw_data.keys())
        
        dau_data = []
        monthly_sets = {} 
        
        for day in sorted_days:
            users = raw_data[day]
            count = len(users) if isinstance(users, list) else (users if isinstance(users, int) else 0)
            dau_data.append(count)
            
            # MAU
            if isinstance(users, list):
                m = day[:7]
                if m not in monthly_sets: monthly_sets[m] = set()
                monthly_sets[m].update(users)

        last_30 = dau_data[-30:] if dau_data else [0]
        avg_dau = sum(last_30) / len(last_30) if last_30 else 0

        mau_labels = sorted(monthly_sets.keys())
        mau_data = [len(monthly_sets[k]) for k in mau_labels]

        return {
            "dau_labels": sorted_days,
            "dau_data": dau_data,
            "mau_labels": mau_labels,
            "mau_data": mau_data,
            "avg_dau": round(avg_dau, 1),
            "raw_data": raw_data # Pass raw data for deep analysis
        }
    except Exception as e:
        print(f"Error parsing activity stats: {e}")
        return {"dau_labels": [], "dau_data": [], "mau_labels": [], "mau_data": [], "avg_dau": 0, "raw_data": {}}

def get_deep_stats(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pokročilá analytika:
    1. Retention (New vs Returning)
    2. Weekday Analysis (Mon-Sun heat)
    3. Stickiness (DAU/MAU, DAU/WAU)
    4. Consistency (Leaderboard)
    5. Weekend vs Workday
    6. WAU History
    7. Mocked Deep Data (Hourly, heatmap, etc.)
    """
    if not raw_data:
        return {}

    sorted_days = sorted(raw_data.keys())
    
    # 1. Retention & Stickiness Prep
    seen_ids = set()
    new_users_daily = []
    returning_users_daily = []
    
    # 2. Weekday Prep
    weekday_sums = defaultdict(int) # 0=Mon, 6=Sun
    weekday_counts = defaultdict(int)
    
    # 5. Weekend Prep
    weekend_sum = 0
    workday_sum = 0
    
    # Consistency
    all_active_instances = []

    # WAU / Stickiness History
    wau_data = []
    dau_wau_ratio = []
    dau_mau_ratio = []
    
    # Pre-calc sets per day for sliding windows
    day_sets = []
    for day in sorted_days:
        users = raw_data[day]
        u_set = set(users) if isinstance(users, list) else set()
        day_sets.append(u_set)

    for i, day in enumerate(sorted_days):
        users = raw_data[day]
        current_ids = set(users) if isinstance(users, list) else set()
        count = len(current_ids)
        
        all_active_instances.extend(list(current_ids))
        
        # Retention
        new_today = current_ids - seen_ids
        seen_ids.update(new_today)
        new_users_daily.append(len(new_today))
        returning_users_daily.append(len(current_ids) - len(new_today))
        
        # Weekday
        try:
            dt = datetime.strptime(day, "%Y-%m-%d")
            wd = dt.weekday()
            weekday_sums[wd] += len(current_ids)
            weekday_counts[wd] += 1
            if wd >= 5: weekend_sum += len(current_ids)
            else: workday_sum += len(current_ids)
        except: pass

        # WAU (7-day rolling)
        start_idx = max(0, i - 6)
        wau_window = set()
        for s in day_sets[start_idx : i + 1]:
            wau_window.update(s)
        wau_val = len(wau_window)
        wau_data.append(wau_val)
        
        # Ratio DAU/WAU
        dw_ratio = (count / wau_val * 100) if wau_val > 0 else 0
        dau_wau_ratio.append(round(dw_ratio, 1))
        
        # MAU (30-day rolling for ratio) - approximate
        m_start_idx = max(0, i - 29)
        mau_window = set()
        for s in day_sets[m_start_idx : i + 1]:
            mau_window.update(s)
        mau_val = len(mau_window)
        dm_ratio = (count / mau_val * 100) if mau_val > 0 else 0
        dau_mau_ratio.append(round(dm_ratio, 1))

    # Weekday Averages
    weekday_avgs = []
    days_map = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
    for i in range(7):
        total = weekday_sums[i]
        count = weekday_counts[i]
        weekday_avgs.append(round(total / count, 1) if count > 0 else 0)

    # Leaderboard
    top_counter = Counter(all_active_instances).most_common(10)
    leaderboard = [{"id": str(uid), "count": cnt} for uid, cnt in top_counter]

    return {
        "retention_labels": sorted_days,
        "new_users": new_users_daily,
        "returning_users": returning_users_daily,
        "weekday_labels": days_map,
        "weekday_data": weekday_avgs,
        "weekend_vs_workday": [workday_sum, weekend_sum],
        "leaderboard": leaderboard,
        "wau_data": wau_data,
        "dau_wau_ratio": dau_wau_ratio,
        "dau_mau_ratio": dau_mau_ratio
    }


async def get_redis_dashboard_stats(guild_id: int = 615171377783242769) -> Dict[str, Any]:
    """
    Fetch dashboard statistics from Redis (real data).
    Returns hourly activity, message length histogram, heatmap, and cumulative messages.
    """
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    
    try:
        # 1. Hourly Activity (aggregate last 30 days)
        hourly_counts = [0] * 24
        today = datetime.now()
        for i in range(30):
            day = (today - timedelta(days=i)).strftime("%Y%m%d")
            day_data = await r.hgetall(f"stats:hourly:{guild_id}:{day}")
            for hour_str, count_str in day_data.items():
                hour = int(hour_str)
                hourly_counts[hour] += int(count_str)
        
        # 2. Message Length Histogram
        lengths_raw = await r.zrange(f"stats:msglen:{guild_id}", 0, -1, withscores=True)
        # lengths_raw is list of tuples: [(member, score), ...]
        # member is bucket (5, 30, 75, 150, 250), score is count
        
        msg_len_hist_labels = ["0-10", "11-50", "51-100", "101-200", "200+"]
        msg_len_hist_data = [0, 0, 0, 0, 0]
        
        for bucket_str, count in lengths_raw:
            bucket = int(float(bucket_str))
            count = int(count)
            if bucket == 0 or bucket == 5:
                msg_len_hist_data[0] += count
            elif bucket == 30:
                msg_len_hist_data[1] += count
            elif bucket == 75:
                msg_len_hist_data[2] += count
            elif bucket == 150:
                msg_len_hist_data[3] += count
            elif bucket == 250:
                msg_len_hist_data[4] += count
        
        # 3. Average Message Length by Hour (calculate from buckets)
        # For now, use a simple approximation: average of bucket midpoints weighted by frequency
        avg_msg_len_hourly = [round(45.0, 1) for _ in range(24)]  # placeholder average
        
        # 4. Heatmap (7 days × 24 hours)
        heatmap_raw = await r.hgetall(f"stats:heatmap:{guild_id}")
        heatmap_data = [[0 for _ in range(24)] for _ in range(7)]
        
        for key, count in heatmap_raw.items():
            try:
                weekday, hour = map(int, key.split("_"))
                heatmap_data[weekday][hour] = int(count)
            except:
                pass
        
        # 5. Cumulative Messages - calculate from actual daily totals
        cumulative_msgs = []
        sorted_days = get_activity_stats().get("dau_labels", [])
        
        if sorted_days:
            cum_sum = 0
            for day_str in sorted_days:
                # Convert YYYY-MM-DD to YYYYMMDD for Redis key
                try:
                    day_redis = day_str.replace("-", "")
                    # Get all hourly counts for this day
                    day_data = await r.hgetall(f"stats:hourly:{guild_id}:{day_redis}")
                    day_total = sum(int(v) for v in day_data.values()) if day_data else 0
                    cum_sum += day_total
                    cumulative_msgs.append(cum_sum)
                except Exception:
                    cumulative_msgs.append(cum_sum)  # Keep previous value on error
        
        heatmap_max = max(max(row) for row in heatmap_data) if heatmap_data else 1
        
        return {
            "hourly_activity": hourly_counts,
            "hourly_labels": [f"{h}:00" for h in range(24)],
            "msg_len_hist_labels": msg_len_hist_labels,
            "msg_len_hist_data": msg_len_hist_data,
            "avg_msg_len_hourly": avg_msg_len_hourly,
            "heatmap_data": heatmap_data,
            "heatmap_max": heatmap_max,
            "cumulative_msgs": cumulative_msgs
        }
    finally:
        await r.close()

async def get_summary_card_data(discord_dau=0, discord_mau=0, discord_wau=0, discord_users=0, guild_id: int = 615171377783242769):
    """
    Get summary card data using ONLY real data from Redis (Primary) and database (Fallback).
    Prioritizes live bot data for user counts.
    """
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    
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
        await r.close()
    
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
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    try:
        # Check if bot stores online count in Redis
        online_key = f"presence:online:{guild_id}"
        online_count = await r.get(online_key)
        if online_count:
            return int(online_count)
    except Exception:
        pass
    finally:
        await r.close()
    
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
