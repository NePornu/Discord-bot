import asyncio
from shared.redis_client import get_redis
import time

async def check():
    r = await get_redis()
    gid = "615171377783242769"
    
    val1 = await r.get(f"stats:total_msgs:{gid}")
    print(f"Total Messages (T=0): {val1}")
    
    # Wait 5 seconds to see if it changes
    await asyncio.sleep(5)
    
    val2 = await r.get(f"stats:total_msgs:{gid}")
    print(f"Total Messages (T=5): {val2}")
    
    if val1 == val2:
        print("No change detected in 5 seconds.")
    else:
        print(f"Change detected: {int(val2) - int(val1)} messages.")

    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
