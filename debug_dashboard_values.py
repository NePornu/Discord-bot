import asyncio
import sys
import os

# Add path to sys.path to ensure imports work
sys.path.append(os.getcwd())

from dashboard.utils import get_summary_card_data, get_redis_dashboard_stats

async def main():
    print("--- DEBUGGING DASHBOARD VALUES ---")
    try:
        # Test 1: Summary Data (Total Members)
        summary = await get_summary_card_data()
        print(f"Summary Data: {summary}")
        print(f"Total Members (Discord Users): {summary.get('discord', {}).get('users')}")
        
        # Test 2: Deep Stats (Heatmap checking too)
        deep = await get_redis_dashboard_stats()
        print(f"Deep Stats Keys: {deep.keys()}")
        print(f"Heatmap Max: {deep.get('heatmap_max')}")
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
