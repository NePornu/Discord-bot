import asyncio
from web.backend.utils import get_redis

async def check_dau():
    r = await get_redis()
    guild_id = 615171377783242769
    keys = await r.keys(f"hll:dau:{guild_id}:*")
    print(f"DAU keys found: {len(keys)}")
    if keys:
        decoded = sorted([k.split(':')[-1] for k in keys])
        print(f"Earliest: {decoded[0]}, Latest: {decoded[-1]}")
    await r.close()

if __name__ == "__main__":
    asyncio.run(check_dau())
