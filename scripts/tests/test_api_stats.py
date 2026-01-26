import asyncio
import json
from web.backend.utils import get_channel_distribution, get_redis
from web.backend.main import get_discord_channels

async def test_api():
    gid = 615171377783242769
    start_date = "2019-03-01"
    end_date = "2026-01-21"
    
    print(f"Testing /api/channel-stats for GID {gid} from {start_date} to {end_date}")
    
    dist = await get_channel_distribution(gid, start_date=start_date, end_date=end_date)
    print(f"Distribution length: {len(dist)}")
    
    channels = await get_discord_channels(gid)
    cmap = {str(c['id']): c['name'] for c in channels}
    
    for d in dist:
        d['name'] = cmap.get(str(d['channel_id']), f"#{d['channel_id']}")
        print(f"Channel: {d['name']}, Count: {d['count']} (Type: {type(d['count'])})")

if __name__ == "__main__":
    asyncio.run(test_api())
