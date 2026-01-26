import asyncio
from shared.redis_client import get_redis

async def check():
    r = await get_redis()
    gid = "615171377783242769"
    dates = ["20260119", "20260120", "20260121"]
    
    for d_str in dates:
        print(f"\n--- {d_str} ---")
        # Hourly total
        h = await r.hgetall(f"stats:hourly:{gid}:{d_str}")
        h_total = sum(int(v) for v in h.values()) if h else 0
        print(f"Hourly total: {h_total}")
        
        # Channel totals
        c_keys = await r.keys(f"stats:channel:{gid}:*:{d_str}")
        c_total = 0
        for k in c_keys:
            v = await r.get(k)
            c_total += int(v) if v else 0
        print(f"Channel total (from daily keys): {c_total} (Keys found: {len(c_keys)})")
        
        # User daily
        u_lb = await r.zcard(f"stats:user_daily:{gid}:{d_str}")
        print(f"User daily entries: {u_lb}")

    all_time = await r.get(f"stats:total_msgs:{gid}")
    print(f"\nAll-time total: {all_time}")
    
    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
