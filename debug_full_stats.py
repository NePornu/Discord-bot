
import asyncio
from web.backend.utils import (
    get_activity_stats, 
    get_redis_dashboard_stats, 
    load_member_stats,
    get_redis
)
import datetime
import json

async def test():
    gid = 615171377783242769
    s_date = "2025-12-21"
    e_date = "2026-01-20"
    
    print(f"--- Debugging Stats for Guild {gid} [{s_date} to {e_date}] ---")
    
    # 1. Activity Stats (DAU)
    print("\n1. Activity Stats (DAU)...")
    try:
        act = await get_activity_stats(gid, start_date=s_date, end_date=e_date)
        print(f"   Avg DAU: {act.get('avg_dau')}")
        data = act.get('dau_data', [])
        print(f"   DAU Data (len={len(data)}): {data}")
        print(f"   Has Non-Zero? {any(v > 0 for v in data)}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # 2. Redis Dashboard Stats (Hourly, Heatmap)
    print("\n2. Redis Dashboard Stats (Hourly, Heatmap)...")
    try:
        dash = await get_redis_dashboard_stats(gid, start_date=s_date, end_date=e_date)
        
        hourly = dash.get('hourly_activity', [])
        print(f"   Hourly Activity (len={len(hourly)}): {hourly}")
        print(f"   Sum Hourly: {sum(hourly)}")
        
        hm = dash.get('heatmap_data', [])
        flat_hm = [val for row in hm for val in row] if hm else []
        print(f"   Heatmap Max: {dash.get('heatmap_max')}")
        print(f"   Heatmap Sum: {sum(flat_hm)}")
        
        msglen = dash.get('msg_len_hist_data', [])
        print(f"   Msg Len Data: {msglen}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # 3. Member Stats (Growth)
    print("\n3. Member Stats (Growth)...")
    try:
        mem = await load_member_stats(gid, start_date=s_date, end_date=e_date)
        joins = mem.get('joins', [])
        leaves = mem.get('leaves', [])
        print(f"   Joins (len={len(joins)}): {joins}")
        print(f"   Leaves (len={len(leaves)}): {leaves}")
        print(f"   Sum Joins: {sum(joins)}")
    except Exception as e:
        print(f"   ERROR: {e}")
        
    await (await get_redis()).close()

if __name__ == "__main__":
    asyncio.run(test())
