import asyncio
from shared.redis_client import get_redis

async def check():
    r = await get_redis()
    days = ["20260119", "20260120", "20260121"]
    gid = "615171377783242769"
    for d in days:
        k_dau = f"hll:dau:{gid}:{d}"
        ex = await r.exists(k_dau)
        print(f"Key {k_dau} exists: {ex}")
        if ex:
             cnt = await r.pfcount(k_dau)
             print(f"  Count: {cnt}")
        
        ex_h = await r.exists(f"stats:hourly:{gid}:{d}")
        print(f"Key stats:hourly:{gid}:{d} exists: {ex_h}")

        chan_keys = await r.keys(f"stats:channel:{gid}:*:{d}")
        print(f"Daily channel keys for {d}: {len(chan_keys)}")
    
    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
