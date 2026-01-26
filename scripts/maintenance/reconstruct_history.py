import discord
import asyncio
import os
import sys
import redis.asyncio as redis
from datetime import datetime

# Add root to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.dashboard_secrets import BOT_TOKEN
except ImportError:
    print("Error: BOT_TOKEN not found in config/dashboard_secrets.py")
    sys.exit(1)

# Intents
intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)

async def reconstruct_guild(guild, r):
    print(f"Processing guild: {guild.name} ({guild.id})")
    
    joins_by_month = {}
    total_members = 0
    
    print("Fetching members...")
    async for member in guild.fetch_members(limit=None):
        total_members += 1
        if member.joined_at:
            # Format: YYYY-MM
            key = member.joined_at.strftime("%Y-%m")
            joins_by_month[key] = joins_by_month.get(key, 0) + 1
            
    print(f"Fetched {total_members} members. Found history spanning {len(joins_by_month)} months.")
    
    # Store in Redis
    # stats:joins:GUILD_ID -> Hash { "2024-01": 5, "2024-02": 12 ... }
    redis_key = f"stats:joins:{guild.id}"
    
    # We overwrite to ensure clean history
    if joins_by_month:
        await r.delete(redis_key)
        await r.hset(redis_key, mapping=joins_by_month)
        print(f"✅ Saved history to Redis key: {redis_key}")
    else:
        print("⚠️ No join dates found?")

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    
    # Use centralized Redis client
    from shared.redis_client import get_redis
    r = await get_redis()
    
    for guild in client.guilds:
        await reconstruct_guild(guild, r)
        
    await r.aclose() # close the client, not the pool necessarily?
    # redis-py 4.x has .close() but for pool it's different. 
    # Just client.close() and exit is fine.
    await client.close()

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("No token.")
    else:
        client.run(BOT_TOKEN)
