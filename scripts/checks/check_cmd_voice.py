import asyncio
from shared.redis_client import get_redis

async def check():
    r = await get_redis()
    gid = "615171377783242769"
    cmd = await r.hgetall(f"stats:commands:{gid}")
    voice = await r.zcard(f"stats:voice_duration:{gid}")
    print(f"Commands count: {len(cmd)}")
    print(f"Voice LB size: {voice}")
    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
