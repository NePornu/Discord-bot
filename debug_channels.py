import asyncio
import redis.asyncio as redis
from web.backend.utils import get_redis

async def check_channel_stats():
    r = await get_redis()
    try:
        keys = await r.keys("stats:channel:*")
        print(f"Total stats:channel keys: {len(keys)}")
        if keys:
            # Check a few
            for k in keys[:5]:
                val = await r.get(k)
                print(f"Key: {k}, Value: {val}")
        
        # Check totals
        guild_id = 615171377783242769
        totals = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, -1, withscores=True)
        print(f"Total channels in guild: {len(totals)}")
        for cid, score in totals[:5]:
            print(f"Channel ID: {cid.decode()}, Total Score: {score}")

    finally:
        await r.close()

if __name__ == "__main__":
    asyncio.run(check_channel_stats())
