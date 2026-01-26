import asyncio
import json
from web.backend.utils import get_redis_dashboard_stats

async def test():
    gid = 615171377783242769
    start_date = "2026-01-19"
    end_date = "2026-01-20"
    
    print(f"Testing stats for GID {gid} from {start_date} to {end_date}")
    result = await get_redis_dashboard_stats(gid, start_date=start_date, end_date=end_date)
    
    # Check peak analysis
    print("\nPeak Analysis:")
    print(json.dumps(result.get("peak_analysis", {}), indent=2))
    
    # Check heatmap sum
    hm = result.get("heatmap_data", [])
    total_msgs = sum(sum(row) for row in hm)
    print(f"\nHeatmap total messages (sum): {total_msgs}")

if __name__ == "__main__":
    asyncio.run(test())
