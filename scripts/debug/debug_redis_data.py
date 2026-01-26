import asyncio
import redis.asyncio as redis
from web.backend.utils import get_redis
from datetime import datetime, timedelta

async def check_data():
    r = await get_redis()
    try:
        guild_id = 615171377783242769
        keys = await r.keys(f"stats:channel:{guild_id}:*")
        print(f"Total keys found for guild {guild_id}: {len(keys)}")
        
        if keys:
            # Sort keys to see date range
            decoded_keys = sorted([k.split(':') for k in keys], key=lambda x: x[-1])
            print(f"Earliest key date: {decoded_keys[0][-1]}")
            print(f"Latest key date: {decoded_keys[-1][-1]}")
            
            # Check a few random values
            for k in keys[:5]:
                val = await r.get(k)
                print(f"Key: {k}, Value: {val}")

        # Check all-time totals
        totals = await r.zrevrange(f"stats:channel_total:{guild_id}", 0, -1, withscores=True)
        print(f"\nAll-time Channel Totals (Top 5):")
        for cid, score in totals[:5]:
            print(f"  Channel {cid}: {score}")

    finally:
        await r.close()

if __name__ == "__main__":
    asyncio.run(check_data())
