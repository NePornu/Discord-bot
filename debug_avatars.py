import asyncio
import redis.asyncio as redis
import os

async def check_avatars():
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    guild_id = "615171377783242769"
    
    print("--- Checking Avatars for Active Users ---")
    keys = []
    async for k in r.scan_iter(f"events:action:{guild_id}:*"):
        keys.append(k)
        
    print(f"Found {len(keys)} action keys.")
    
    count = 0
    for k in keys[:10]: # Check first 10
        uid = k.split(":")[-1]
        info = await r.hgetall(f"user:info:{uid}")
        print(f"User {uid}: Name={info.get('name')}, Avatar={info.get('avatar')}")
        count += 1
        
    await r.close()

if __name__ == "__main__":
    asyncio.run(check_avatars())
