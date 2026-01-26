import asyncio
import redis.asyncio as redis
import json
import os
import sys

sys.path.append('/root/discord-bot')

async def debug_redis():
    try:
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        guild_id = "615171377783242769"
        
        print(f"--- Debugging Activity Logic for Guild: {guild_id} ---")
        
        # 1. Simulate Time Range
        import datetime
        now = datetime.datetime.now()
        start_dt = now - datetime.timedelta(days=30)
        ts_start = start_dt.timestamp()
        ts_end = now.timestamp()
        print(f"Time Range: {start_dt} ({ts_start}) - {now} ({ts_end})")
        
        # 2. Scan Actions "Manual" check
        found_keys = 0
        valid_actions = 0
        async for key in r.scan_iter(f"events:action:{guild_id}:*"):
            found_keys += 1
            # Check ZCOUNT
            count = await r.zcount(key, ts_start, ts_end)
            if count > 0:
                print(f"  -> Key {key} has {count} actions in range!")
                valid_actions += 1
            else:
                # Debug why 0?
                total = await r.zcard(key)
                if total > 0:
                    last = await r.zrange(key, -1, -1, withscores=True)
                    print(f"  -> Key {key} has 0 in range, but {total} total. Last: {last}")
        
        print(f"Found {found_keys} generic keys, {valid_actions} with actions in 30d range.")

        # 3. Test get_deep_stats_redis logic (Embedded to avoid import issues)
        from collections import defaultdict
        staff_stats = defaultdict(lambda: {"actions": 0, "voice_time": 0, "weighted": 0})
        
        async for key in r.scan_iter(f"events:action:{guild_id}:*"):
            uid = key.split(":")[-1]
            c = await r.zcount(key, ts_start, ts_end)
            if c > 0:
                staff_stats[uid]["actions"] += c
                staff_stats[uid]["weighted"] += c * 60 # Dummy weight

        print(f"Staff Stats (Actions Only): {len(staff_stats)} users")
        for uid, stats in staff_stats.items():
            print(f"  User {uid}: {stats}")
            
            # Check User Info
            info = await r.hgetall(f"user:info:{uid}")
            print(f"    Info: {info}")

        await r.close()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_redis())
