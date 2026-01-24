import asyncio
import json
from web.backend.utils import get_channel_distribution

async def test():
    gid = 615171377783242769
    # Recent range that likely has NO daily data yet because bot is outdated
    start_date = "2026-01-20"
    end_date = "2026-01-21"
    
    print(f"Testing channel distribution for GID {gid} from {start_date} to {end_date}")
    result = await get_channel_distribution(gid, start_date=start_date, end_date=end_date)
    print(f"Result: {json.dumps(result, indent=2)}")

if __name__ == "__main__":
    asyncio.run(test())
