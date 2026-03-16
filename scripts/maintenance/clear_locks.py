import asyncio
import os
import sys
import redis.asyncio as redis

# Add project root to path for imports if needed
sys.path.append('/root/discord-bot')

async def clear_locks():
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    print(f"Connecting to Redis at {redis_url}...")
    try:
        r = redis.from_url(redis_url, decode_responses=True)
        
        # Common lock keys
        locks = ["bot:lock:primary", "bot:lock:lite", "bot:lock:worker"]
        
        for lock in locks:
            val = await r.get(lock)
            if val:
                print(f"Removing lock {lock} (Held by PID: {val})")
                await r.delete(lock)
            else:
                print(f"Lock {lock} is not set.")
                
        await r.aclose()
        print("Done.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(clear_locks())
