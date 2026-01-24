import asyncio
from shared.redis_client import get_redis

async def check():
    r = await get_redis()
    gid = "615171377783242769"
    
    print(f"--- Redis Check for GID {gid} ---")
    
    # 1. Channel Total
    ct_size = await r.zcard(f"stats:channel_total:{gid}")
    print(f"stats:channel_total size: {ct_size}")
    if ct_size > 0:
        top_ch = await r.zrevrange(f"stats:channel_total:{gid}", 0, 2, withscores=True)
        print(f"  Top 3 Channels: {top_ch}")

    # 2. Leaderboard All-time
    lb_size = await r.zcard(f"leaderboard:messages:{gid}")
    print(f"leaderboard:messages size: {lb_size}")
    if lb_size > 0:
        top_us = await r.zrevrange(f"leaderboard:messages:{gid}", 0, 2, withscores=True)
        print(f"  Top 3 Users: {top_us}")

    # 3. User Daily (for today)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    ud_size = await r.zcard(f"stats:user_daily:{gid}:{today}")
    print(f"stats:user_daily:{today} size: {ud_size}")

    # 4. Joins/Leaves
    joins = await r.hlen(f"stats:joins:{gid}")
    leaves = await r.hlen(f"stats:leaves:{gid}")
    print(f"Traffic keys count: joins={joins}, leaves={leaves}")

    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
