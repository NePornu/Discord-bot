
import asyncio
from web.backend.utils import get_redis
import datetime

async def test():
    gid = 615171377783242769
    r = await get_redis()
    
    # Check yesterday (2026-01-20)
    key = f"hll:dau:{gid}:20260120"
    count = await r.pfcount(key)
    print(f"Key: {key}, Count: {count}")
    
    # Check today (2026-01-21)
    key_today = f"hll:dau:{gid}:20260121"
    count_today = await r.pfcount(key_today)
    print(f"Key: {key_today}, Count: {count_today}")
    
    # Check ANY DAU key
    keys = await r.keys(f"hll:dau:{gid}:*")
    print(f"Total DAU keys found: {len(keys)}")
    if keys:
        print(f"Sample keys: {keys[:5]}")

    await r.close()

if __name__ == "__main__":
    asyncio.run(test())
