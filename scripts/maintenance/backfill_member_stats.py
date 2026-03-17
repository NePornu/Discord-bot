import discord
import asyncio
import os
import sys
import json
import redis.asyncio as redis
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

# Manual .env loading (to avoid dependency on python-dotenv)
env_path = os.path.join(ROOT_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val.strip('"').strip("'")

# Try to get token from environment
token = os.getenv("BOT_TOKEN")

if not token:
    print("Error: BOT_TOKEN not found in environment or .env file.")
    sys.exit(1)

# Configuration
GUILD_ID = int(os.getenv("GUILD_ID", 615171377783242769))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JSON_PATH = Path("data/member_counts.json")

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)

async def backfill():
    print("=" * 60)
    print("Starting Member Statistics Backfill")
    print("=" * 60)

    r = redis.from_url(REDIS_URL, decode_responses=True)
    
    # 1. Load historical data from JSON
    historical_joins = {}
    historical_leaves = {}
    
    if JSON_PATH.exists():
        print(f"Loading historical data from {JSON_PATH}...")
        try:
            data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            for month, stats in data.items():
                if isinstance(stats, dict):
                    historical_joins[month] = stats.get("joins", 0)
                    historical_leaves[month] = stats.get("leaves", 0)
            print(f"✓ Loaded {len(data)} months from JSON.")
        except Exception as e:
            print(f"⚠️ Error loading JSON: {e}")
    else:
        print(f"ℹ️ {JSON_PATH} not found, proceeding with Discord data only.")

    # 2. Get current members from Discord
    print("\nConnecting to Discord to fetch current members...")
    
    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")
        guild = client.get_guild(GUILD_ID)
        if not guild:
            print(f"ERROR: Could not find guild {GUILD_ID}")
            await client.close()
            return

        print(f"Processing guild: {guild.name}")
        
        discord_joins = {}
        total_members = 0
        
        async for member in guild.fetch_members(limit=None):
            total_members += 1
            if member.joined_at:
                month_key = member.joined_at.strftime("%Y-%m")
                discord_joins[month_key] = discord_joins.get(month_key, 0) + 1
        
        print(f"Fetched {total_members} members. Found history spanning {len(discord_joins)} months.")

        # 3. Merge data
        # Note: Discord data for joins will be "at least" what we see now.
        # JSON data might have more (including people who already left).
        # We take the MAX of JSON and Discord for joins to be safe.
        
        final_joins = historical_joins.copy()
        for month, count in discord_joins.items():
            if month in final_joins:
                final_joins[month] = max(final_joins[month], count)
            else:
                final_joins[month] = count
                
        # Leaves usually come mostly from JSON as Discord doesn't keep historical leave logs long-term
        final_leaves = historical_leaves.copy()

        # 4. Save to Redis
        print("\nSaving statistics to Redis...")
        join_key = f"stats:joins:{GUILD_ID}"
        leave_key = f"stats:leaves:{GUILD_ID}"
        
        pipe = r.pipeline()
        # We overwrite to ensure clean state based on our best current knowledge
        if final_joins:
            pipe.delete(join_key)
            pipe.hset(join_key, mapping=final_joins)
        if final_leaves:
            pipe.delete(leave_key)
            pipe.hset(leave_key, mapping=final_leaves)
            
        await pipe.execute()
        
        print(f"✅ Final stats saved to Redis:")
        print(f"   Joins: {len(final_joins)} months processed")
        print(f"   Leaves: {len(final_leaves)} months processed")
        print("\nBackfill complete!")
        
        await r.close()
        await client.close()

    try:
        await client.start(token)
    except Exception as e:
        print(f"Error: {e}")
        await r.close()

if __name__ == "__main__":
    asyncio.run(backfill())
