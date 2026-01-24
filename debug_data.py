import asyncio
from shared.redis_client import get_redis

async def check():
    r = await get_redis()
    gid = "615171377783242769"
    
    print("--- All-time Channel Totals ---")
    data = await r.zrevrange(f"stats:channel_total:{gid}", 0, 10, withscores=True)
    for cid, count in data:
        print(f"Channel {cid}: {count}")

    print("\n--- Daily Channel Totals (Today) ---")
    today = "20260121"
    keys = await r.keys(f"stats:channel:{gid}:*:{today}")
    for k in keys:
        val = await r.get(k)
        print(f"Key {k}: {val}")

    print("\n--- Leaderboard (Top 5) ---")
    lb = await r.zrevrange(f"leaderboard:messages:{gid}", 0, 4, withscores=True)
    for uid, count in lb:
        print(f"User {uid}: {count}")

    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
