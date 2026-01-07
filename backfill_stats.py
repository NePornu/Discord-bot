#!/usr/bin/env python3
"""
Backfill script to populate Redis with historical Discord message data.
Fetches messages from Discord API and generates statistics for dashboard.
"""
import asyncio
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis
from collections import defaultdict

# Import config - read directly from files to avoid path issues
import os
BOT_TOKEN = None
GUILD_ID = None

# Try reading bot token
token_file = os.path.join(os.path.dirname(__file__), 'bot_token.py')
if os.path.exists(token_file):
    with open(token_file, 'r') as f:
        for line in f:
            if line.startswith('TOKEN'):
                BOT_TOKEN = line.split('=')[1].strip().strip('"').strip("'")
                break

if not BOT_TOKEN:
    print("ERROR: Could not read BOT_TOKEN from bot_token.py")
    exit(1)

# Try reading guild ID
config_file = os.path.join(os.path.dirname(__file__), 'config.py')
if os.path.exists(config_file):
    with open(config_file, 'r') as f:
        for line in f:
            if line.startswith('GUILD_ID'):
                GUILD_ID = int(line.split('=')[1].strip().split('#')[0].strip())
                break

if not GUILD_ID:
    print("ERROR: Could not read GUILD_ID from config.py")
    exit(1)

# Redis configuration
# Use direct IP for running from host, or hostname if in docker network
REDIS_URL = "redis://172.22.0.2:6379/0"

# Key functions (matching activity_hll_optimized.py)
def day_key(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")

def K_HOURLY(gid: int, d: str) -> str:
    return f"stats:hourly:{gid}:{d}"

def K_MSGLEN(gid: int) -> str:
    return f"stats:msglen:{gid}"

def K_HEATMAP(gid: int) -> str:
    return f"stats:heatmap:{gid}"

def K_TOTAL_MSGS(gid: int) -> str:
    return f"stats:total_msgs:{gid}"


async def backfill_channel_history(bot: discord.Client, channel: discord.TextChannel, r: redis.Redis, days_back: int = None):
    """Fetch and process historical messages from a channel."""
    print(f"  Processing #{channel.name}...")
    
    # Calculate cutoff time
    after_date = datetime.utcnow() - timedelta(days=days_back) if days_back else None
    
    msg_count = 0
    total_msgs = 0
    
    daily_stats = defaultdict(lambda: defaultdict(int))  # {date: {hour: count}}
    hll_members = defaultdict(set) # {date: {uids}}
    heatmap_agg = defaultdict(int) # {weekday_hour: count}
    msglen_agg = defaultdict(int)  # {bucket: count}
    
    # 2. Iterate history
    try:
        async for msg in channel.history(limit=None, after=after_date, oldest_first=False):
            if msg.author.bot:
                continue
                
            msg_dt = msg.created_at.replace(tzinfo=timezone.utc)
            if msg_dt < after_date:
                break
            
            # 1. Hourly Stats & HLL
            date_str = msg_dt.strftime("%Y%m%d")
            hour = msg_dt.hour
            daily_stats[date_str][hour] += 1
            hll_members[date_str].add(str(msg.author.id))
            
            # 2. Heatmap (weekday_hour)
            # weekday: 0=Mon, 6=Sun
            hm_key = f"{msg_dt.weekday()}_{hour}"
            heatmap_agg[hm_key] += 1
            
            # 3. Message Lengths
            l = len(msg.content)
            if l == 0: b=0
            elif l<=10: b=5
            elif l<=50: b=30
            elif l<=100: b=75
            elif l<=200: b=150
            else: b=250
            msglen_agg[b] += 1
            
            msg_count += 1
            if msg_count % 500 == 0:
                print(f"    ... processed {msg_count} messages")

    except discord.Forbidden:
        print(f"    SKIP: No permission to read #{channel.name}")
        return 0
    except Exception as e:
        print(f"    ERROR in #{channel.name}: {e}")
        return 0

    if msg_count > 0:
        # PUSH TO REDIS (Atomic batch)
        pipe = r.pipeline()
        gid = channel.guild.id
        
        # Write Hourly
        for d_str, hours in daily_stats.items():
            k = f"stats:hourly:{gid}:{d_str}"
            for h, c in hours.items(): pipe.hincrby(k, str(h), c)
            pipe.expire(k, 60*86400)
            
        # Write HLL
        for d_str, uids in hll_members.items():
            k = f"hll:dau:{gid}:{d_str}"
            pipe.pfadd(k, *uids)
            pipe.expire(k, 40*86400)
            
        # Write Heatmap
        for k, c in heatmap_agg.items():
            pipe.hincrby(f"stats:heatmap:{gid}", k, c)
        pipe.expire(f"stats:heatmap:{gid}", 60*86400)
            
        # Write MsgLen
        for b, c in msglen_agg.items():
            pipe.zincrby(f"stats:msglen:{gid}", c, b)
            
        # Write Total
        pipe.incrby(f"stats:total_msgs:{gid}", msg_count)
        
        await pipe.execute()
        print(f"    ✓ Uploaded {msg_count} messages to Redis")
    
    return msg_count


async def reset_stats(r: redis.Redis, gid: int):
    print("🧹 PRE-FLIGHT: Cleaning old statistics from Redis...")
    try:
        keys = []
        # We need to find all keys related to stats for this guild
        # stats:hourly:GID:DATE, hll:dau:GID:DATE, stats:heatmap:GID, stats:msglen:GID, stats:total_msgs:GID
        match_patterns = [
            f"stats:hourly:{gid}:*",
            f"hll:dau:{gid}:*",
            f"stats:heatmap:{gid}",
            f"stats:msglen:{gid}",
            f"stats:total_msgs:{gid}"
        ]
        
        for pattern in match_patterns:
            async for k in r.scan_iter(pattern):
                keys.append(k)
        
        if keys:
            await r.delete(*keys)
            print(f"   ✓ Deleted {len(keys)} old stat keys (Fresh Start)")
        else:
            print("   ✓ Redis is clean (No old stats found)")
            
    except Exception as e:
        print(f"   ⚠️ Error while resetting stats: {e}")

async def main():
    print("=" * 60)
    print("Discord Message History Backfill Script (FULL HISTORY)")
    print("=" * 60)
    
    # Initialize bot
    intents = discord.Intents.default()
    intents.guilds = True
    
    bot = discord.Client(intents=intents)
    r = redis.from_url(REDIS_URL, decode_responses=True)
    
    @bot.event
    async def on_ready():
        print(f"\n✓ Logged in as {bot.user}")
        print(f"  Guild ID: {GUILD_ID}\n")
        
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            print(f"ERROR: Could not find guild {GUILD_ID}")
            await bot.close()
            return
        
        # 1. Reset Stats
        await reset_stats(r, GUILD_ID)
        
        print(f"Guild: {guild.name}")
        print(f"Total channels: {len(guild.text_channels)}\n")
        
        total_messages = 0
        for channel in guild.text_channels:
            # Full History (days_back=None)
            count = await backfill_channel_history(bot, channel, r, days_back=None)
            total_messages += count
        
        print("\n" + "=" * 60)
        print(f"✓ FULL Backfill complete!")
        print(f"  Total messages processed: {total_messages:,}")
        print("=" * 60)
        
        await r.close()
        await bot.close()
    
    try:
        await bot.start(BOT_TOKEN)
    except KeyboardInterrupt:
        print("\n\nBackfill interrupted by user.")
        await r.close()
        await bot.close()


if __name__ == "__main__":
    print("\n⚠️  This script will fetch ALL message history from Discord API.")
    print("   This may take a LONG time (hours depending on server size).")
    print("   Starting automatically in 2 seconds...\n")
    import time
    time.sleep(2)
    
    asyncio.run(main())
