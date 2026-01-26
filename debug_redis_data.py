import asyncio
import redis.asyncio as redis
import os
import sys

# Add path to import shared modules if needed, but we'll specific connection manually to be safe or use what's available
sys.path.append('/root/discord-bot')

async def check_redis():
    # Use localhost as per config usually
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    
    guild_id = "615171377783242769" # NePornu
    
    print(f"Checking keys for Guild: {guild_id}")
    
    # Check Action Events
    action_keys = []
    async for k in r.scan_iter(f"events:action:{guild_id}:*"):
        action_keys.append(k)
        if len(action_keys) > 10: break
    
    print(f"Found {len(action_keys)}+ action keys.")
    if action_keys:
        print(f"Sample Action Key: {action_keys[0]}")
        type_ = await r.type(action_keys[0])
        print(f"Type: {type_}")
        if type_ == 'zset':
            count = await r.zcard(action_keys[0])
            print(f"Count in ZSET: {count}")
            # Show one
            data = await r.zrange(action_keys[0], 0, -1, withscores=True)
            print(f"Sample logic: {data[0]}")

    # Check Voice Events
    voice_keys = []
    async for k in r.scan_iter(f"events:voice:{guild_id}:*"):
        voice_keys.append(k)
        if len(voice_keys) > 10: break
        
    print(f"Found {len(voice_keys)}+ voice keys.")
    if voice_keys:
        print(f"Sample Voice Key: {voice_keys[0]}")
        
    # Check if there are ANY keys for this guild
    any_keys = []
    async for k in r.scan_iter(f"*{guild_id}*"):
        any_keys.append(k)
        if len(any_keys) > 10: break
    print(f"Total random keys match *{guild_id}*: {len(any_keys)}")
    if any_keys:
        print(f"Examples: {any_keys}")

    await r.close()

if __name__ == "__main__":
    asyncio.run(check_redis())
