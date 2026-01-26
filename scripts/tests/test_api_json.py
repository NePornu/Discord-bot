import asyncio
import json
from web.backend.utils import get_channel_distribution, get_redis
from web.backend.main import get_discord_channels

async def test_api():
    gid = 615171377783242769
    start_date = "2026-01-19"
    end_date = "2026-01-20"
    
    dist = await get_channel_distribution(gid, start_date=start_date, end_date=end_date)
    channels = await get_discord_channels(gid)
    cmap = {str(c['id']): c['name'] for c in channels}
    
    for d in dist:
        d['name'] = cmap.get(str(d['channel_id']), f"#{d['channel_id']}")
    
    print(json.dumps({"channels": dist}, indent=2))

if __name__ == "__main__":
    asyncio.run(test_api())
