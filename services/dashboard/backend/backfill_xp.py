
import asyncio
import redis.asyncio as redis
import sys
import math
import random
sys.path.append('/root/discord-bot')
from shared.redis_client import REDIS_URL



def get_level(xp):
    if xp < 100: return 0
    a, b, c = 5, 50, 100 - xp
    d = (b**2) - (4*a*c)
    if d < 0: return 0
    level = int((-b + math.sqrt(d)) / (2*a))
    return level

async def backfill_xp():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    guild_id = 615171377783242769
    
    xp_key = f"levels:xp:{guild_id}"
    print(f"Starting XP backfill for Guild {guild_id}...")
    
    
    
    
    
    
    
    cursor = "0"
    processed_users = 0
    
    async for key in r.scan_iter(match=f"events:msg:{guild_id}:*"):
        uid = key.split(":")[-1]
        
        
        msgs = await r.zrange(key, 0, -1, withscores=True)
        
        total_xp = 0
        last_xp_time = 0
        
        for _, score in msgs:
            ts = float(score)
            
            
            if ts - last_xp_time >= 60:
                gain = random.randint(15, 25)
                total_xp += gain
                last_xp_time = ts
        
        if total_xp > 0:
            await r.zadd(xp_key, {uid: total_xp})
            processed_users += 1
            if processed_users % 10 == 0:
                print(f"Processed {processed_users} users...")
            
    print(f"Backfill complete. Processed {processed_users} users.")

if __name__ == "__main__":
    asyncio.run(backfill_xp())
