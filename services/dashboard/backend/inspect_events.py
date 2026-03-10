
import asyncio
import redis.asyncio as redis
import sys
sys.path.append('/root/discord-bot')
from shared.python.redis_client import get_redis_client
import json

async def inspect_events():
    r = get_redis_client()
    guild_id = 615171377783242769
    
    print("Scanning for message events...")
    keys = []
    async for key in r.scan_iter(f"events:msg:{guild_id}:*"):
        keys.append(key)
        if len(keys) >= 5: break
        
    for k in keys:
        uid = k.split(":")[-1]
        print(f"\nUser {uid} ({k}):")
        
        items = await r.zrange(k, 0, 4, withscores=True)
        for val, score in items:
            print(f"  [{score}] {val}")

if __name__ == "__main__":
    asyncio.run(inspect_events())
