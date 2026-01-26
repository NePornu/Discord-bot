import asyncio
import sys
import os
import json

# Add project root to path
sys.path.append('/root/discord-bot')

from web.backend.utils import get_deep_stats_redis

async def test_logic():
    print("--- Testing get_deep_stats_redis ---")
    guild_id = 615171377783242769
    start_date = "2025-12-21"
    end_date = "2026-01-20"
    
    print(f"Params: Guild={guild_id}, Start={start_date}, End={end_date}")
    
    try:
        stats = await get_deep_stats_redis(guild_id, start_date=start_date, end_date=end_date)
        
        print(f"Active Staff Count: {stats.get('active_staff_count')}")
        print(f"Total Hours: {stats.get('total_hours_30d')}")
        print(f"Leaderboard Size: {len(stats.get('leaderboard', []))}")
        
        if stats.get('leaderboard'):
            print("Top User:", stats['leaderboard'][0])
        else:
            print("Leaderboard is empty!")
            
    except Exception as e:
        print(f"CRASH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_logic())
