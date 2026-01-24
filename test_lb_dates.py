import asyncio
import json
from web.backend.utils import get_leaderboard_data

async def test():
    gid = 615171377783242769
    start_date = "2026-01-19"
    end_date = "2026-01-20"
    
    print(f"Testing get_leaderboard_data for GID {gid} from {start_date} to {end_date}")
    result = await get_leaderboard_data(gid, start_date=start_date, end_date=end_date)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(test())
