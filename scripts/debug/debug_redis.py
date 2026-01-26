
import asyncio
from web.backend.utils import get_channel_distribution, get_redis
import sys

async def test():
    gid = 615171377783242769
    print(f"Testing fetch for guild {gid}")
    try:
        data = await get_channel_distribution(gid)
        print(f"Result: {data}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
