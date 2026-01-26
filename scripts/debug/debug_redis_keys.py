import asyncio
import redis.asyncio as redis
import os
from datetime import datetime, timedelta

async def main():
    gid = 615171377783242769
    # Suspected IPs
    urls = ["redis://172.22.0.2:6379/0", "redis://localhost:6379/0", "redis://redis-hll:6379/0"]
    r = None
    for url in urls:
        try:
            r = redis.from_url(url, decode_responses=True)
            await asyncio.wait_for(r.ping(), timeout=2.0)
            print(f"Connected to {url}")
            break
        except Exception as e:
            print(f"Failed {url}: {e}")
            r = None
            
    if not r:
        print("Could not connect to Redis")
        return

    # Check keys
    total_msgs = await r.get(f"stats:total_msgs:{gid}")
    print(f"Total Msgs ({gid}): {total_msgs}")
    
    chan_total = await r.zrevrange(f"stats:channel_total:{gid}", 0, -1, withscores=True)
    print(f"Channel Totals ({gid}): {chan_total}")
    
    today = datetime.now().strftime("%Y%m%d")
    chan_daily = await r.keys(f"stats:channel:{gid}:*:*")
    print(f"Daily Channel Keys Count: {len(chan_daily)}")

asyncio.run(main())
