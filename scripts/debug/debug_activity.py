
import asyncio
from web.backend.utils import get_activity_stats, get_redis
import sys

async def test():
    gid = 615171377783242769
    print(f"Testing get_activity_stats for guild {gid}")
    # Simulate the date range from user screenshot: 21.12.2025 - 20.01.2026
    s_date = "2025-12-21"
    e_date = "2026-01-20"
    try:
        data = await get_activity_stats(gid, start_date=s_date, end_date=e_date)
        print(f"Data keys: {data.keys()}")
        print(f"DAU Data Sample: {data['dau_data'][:5]} ... {data['dau_data'][-5:]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
