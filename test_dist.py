import asyncio
import redis.asyncio as redis
from web.backend.utils import get_redis, get_channel_distribution
from datetime import datetime

async def test_dist():
    guild_id = 615171377783242769
    start_date = "2025-01-01"
    end_date = "2026-01-20"
    
    print(f"Testing dist for {guild_id} from {start_date} to {end_date}...")
    dist = await get_channel_distribution(guild_id, start_date, end_date)
    
    print(f"Result count: {len(dist)}")
    for d in dist[:5]:
        print(f"  Channel {d.get('channel_id')}: {d.get('count')}")

if __name__ == "__main__":
    asyncio.run(test_dist())
