#!/usr/bin/env python3
"""
Backfill script to populate Redis with historical Discord message data.
Fetches messages from Discord API and generates statistics for dashboard.
Run with: python3 backfill_stats.py --guild_id <ID> [--token <TOKEN>]
"""
import asyncio
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis
from collections import defaultdict
import argparse
import sys
import os

# Default Config Fallback
BOT_TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config', 'bot_token.py'))
CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config', 'config.py'))

def get_default_config():
    token = None
    gid = None
    
    if os.path.exists(BOT_TOKEN_FILE):
        with open(BOT_TOKEN_FILE, 'r') as f:
            for line in f:
                if line.startswith('TOKEN'):
                    token = line.split('=')[1].strip().strip('"').strip("'")
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                if line.startswith('GUILD_ID'):
                    try: gid = int(line.split('=')[1].strip().split('#')[0].strip())
                    except: pass
    return token, gid

# Redis configuration
REDIS_URL = "redis://172.22.0.2:6379/0"

# Key functions
def day_key(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


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

def K_BACKFILL_PROGRESS(gid: int) -> str:
    return f"backfill:progress:{gid}"

async def report_progress(r: redis.Redis, gid: int, status: str, total_msgs: int = 0, current_channel: str = ""):
    """Report progress to Redis."""
    import json
    data = {
        "status": status,
        "total_messages": total_msgs,
        "current_channel": current_channel,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await r.set(K_BACKFILL_PROGRESS(gid), json.dumps(data), ex=3600)


async def backfill_channel_history(bot: discord.Client, channel: discord.TextChannel, r: redis.Redis, days_back: int = None, current_total: int = 0):
    """Fetch and process historical messages from a channel."""
    print(f"  Processing #{channel.name}...")
    await report_progress(r, channel.guild.id, "processing", current_total, channel.name)
    
    # Calculate cutoff time
    after_date = datetime.utcnow() - timedelta(days=days_back) if days_back else None
    
    msg_count = 0
    
    # Aggregates
    daily_stats = defaultdict(lambda: defaultdict(int))  # {date: {hour: count}}
    hll_members = defaultdict(set) # {date: {uids}}
    heatmap_agg = defaultdict(int) # {weekday_hour: count}
    msglen_agg = defaultdict(int)  # {bucket: count}
    
    # New Aggregates for Leaderboards & Channel Stats
    user_msg_counts = defaultdict(int) # {uid: count}
    user_avg_len_agg = defaultdict(list) # {uid: [len, ...]} -> simplified to sum/count to save RAM? 
    # Storing all lengths for huge servers in RAM is bad. 
    # But for "Top Users" we need average length. 
    # Let's store sum_len and count.
    user_len_sum = defaultdict(int) 
    
    # Channel Stats (Daily)
    # stats:channel:{gid}:{cid}:{date}
    channel_daily_stats = defaultdict(int) # {date: count}
    channel_hourly_stats = defaultdict(int) # {hour: count}
    
    user_event_buffer = defaultdict(dict) # {uid: {data: score}}
    BATCH_SIZE = 500
    
    try:
        async for msg in channel.history(limit=None, after=after_date, oldest_first=False):
            if msg.author.bot:
                continue
                
            msg_dt = msg.created_at.replace(tzinfo=timezone.utc)
            if after_date and msg_dt < after_date:
                break
            
            # Key Vars
            date_str = msg_dt.strftime("%Y%m%d")
            hour = msg_dt.hour
            weekday = msg_dt.weekday()
            uid = msg.author.id
            cid = channel.id
            msg_len = len(msg.content)
            
            # 1. Hourly Stats & HLL (Global)
            daily_stats[date_str][hour] += 1
            hll_members[date_str].add(str(uid))
            
            # 2. Heatmap (Global)
            hm_key = f"{weekday}_{hour}"
            heatmap_agg[hm_key] += 1
            
            # 3. Message Lengths (Global)
            if msg_len == 0: b=0
            elif msg_len <= 10: b=5
            elif msg_len <= 50: b=30
            elif msg_len <= 100: b=75
            elif msg_len <= 200: b=150
            else: b=250
            msglen_agg[b] += 1
            
            # 4. Raw Events (Events:Msg)
            # Necessary for "User Activity" page detailed view
            import json
            evt_key = f"events:msg:{channel.guild.id}:{uid}"
            evt_data = json.dumps({"len": msg_len, "reply": msg.reference is not None})
            user_event_buffer[evt_key][evt_data] = msg_dt.timestamp()

            # 5. Leaderboard Aggregates
            user_msg_counts[uid] += 1
            user_len_sum[uid] += msg_len
            
            # 6. Channel Stats
            channel_daily_stats[date_str] += 1
            channel_hourly_stats[hour] += 1

            msg_count += 1
            
            if msg_count % BATCH_SIZE == 0:
                print(f"    ... processed {msg_count} messages")
                await report_progress(r, channel.guild.id, "processing", current_total + msg_count, channel.name)
                
                # --- INCREMENTAL PUSH TO REDIS ---
                pipe = r.pipeline()
                
                # Flush events buffer
                for k, v in user_event_buffer.items():
                    pipe.zadd(k, v)
                user_event_buffer.clear()
                
                # 1. Global Hourly
                gid = channel.guild.id
                for d_str, hours in daily_stats.items():
                    k = f"stats:hourly:{gid}:{d_str}"
                    for h, c in hours.items(): pipe.hincrby(k, str(h), c)
                    pipe.expire(k, 60*86400)
                daily_stats.clear() # Clear after push
                
                # 2. Global HLL
                for d_str, uids in hll_members.items():
                    k = f"hll:dau:{gid}:{d_str}"
                    pipe.pfadd(k, *uids)
                    pipe.expire(k, 40*86400)
                hll_members.clear()

                # 3. Global Heatmap
                for k, c in heatmap_agg.items():
                    pipe.hincrby(f"stats:heatmap:{gid}", k, c)
                pipe.expire(f"stats:heatmap:{gid}", 60*86400)
                heatmap_agg.clear()
                
                # 4. Global MsgLen
                for b, c in msglen_agg.items():
                    pipe.zincrby(f"stats:msglen:{gid}", c, b)
                msglen_agg.clear()
                    
                # 5. Global Total
                pipe.incrby(f"stats:total_msgs:{gid}", BATCH_SIZE) # Approximate but safe if we push every batch
                
                # 6. Channel Specific Stats
                pipe.zincrby(f"stats:channel_total:{gid}", BATCH_SIZE, cid)
                pipe.hset(f"channel:info:{cid}", mapping={"name": channel.name})
                
                # Daily/Hourly per channel
                for d_str, c in channel_daily_stats.items():
                     k = f"stats:channel:{gid}:{cid}:{d_str}"
                     pipe.incrby(k, c)
                     pipe.expire(k, 60*86400)
                channel_daily_stats.clear()

                k_ch_hour = f"stats:channel_hourly:{gid}:{cid}"
                for h, c in channel_hourly_stats.items():
                    pipe.hincrby(k_ch_hour, h, c)
                pipe.expire(k_ch_hour, 60*86400)
                channel_hourly_stats.clear()
                     
                # 7. Leaderboard
                for uid, c in user_msg_counts.items():
                    pipe.zincrby(f"leaderboard:messages:{gid}", c, uid)
                    
                    # Avg len hack: just push one sample
                    avg = int(user_len_sum[uid] / c)
                    k_len = f"leaderboard:msg_lengths:{gid}:{uid}"
                    pipe.lpush(k_len, avg)
                user_msg_counts.clear()
                user_len_sum.clear()

                await pipe.execute()
                # -------------------------------

    except discord.Forbidden:
        print(f"    SKIP: No permission to read #{channel.name}")
        return 0
    except Exception as e:
        print(f"    ERROR in #{channel.name}: {e}")
        return 0

    # Remaining flush (same logic but for leftovers)
    if msg_count % BATCH_SIZE != 0:
        gid = channel.guild.id
        cid = channel.id
        pipe = r.pipeline()
        
        # Flush events
        if user_event_buffer:
            for k, v in user_event_buffer.items(): pipe.zadd(k, v)
            user_event_buffer.clear()

        # Flush aggregators
        for d_str, hours in daily_stats.items():
            k = f"stats:hourly:{gid}:{d_str}"
            for h, c in hours.items(): pipe.hincrby(k, str(h), c)
            pipe.expire(k, 60*86400)
            
        for d_str, uids in hll_members.items():
            k = f"hll:dau:{gid}:{d_str}"
            pipe.pfadd(k, *uids)
            pipe.expire(k, 40*86400)
            
        for k, c in heatmap_agg.items():
            pipe.hincrby(f"stats:heatmap:{gid}", k, c)
            
        for b, c in msglen_agg.items():
            pipe.zincrby(f"stats:msglen:{gid}", c, b)
            
        leftover = msg_count % BATCH_SIZE
        pipe.incrby(f"stats:total_msgs:{gid}", leftover)
        pipe.zincrby(f"stats:channel_total:{gid}", leftover, cid)
        pipe.hset(f"channel:info:{cid}", mapping={"name": channel.name})
        
        for d_str, c in channel_daily_stats.items():
             pipe.incrby(f"stats:channel:{gid}:{cid}:{d_str}", c)
             
        for h, c in channel_hourly_stats.items():
            pipe.hincrby(f"stats:channel_hourly:{gid}:{cid}", h, c)
             
        for uid, c in user_msg_counts.items():
            pipe.zincrby(f"leaderboard:messages:{gid}", c, uid)
            avg = int(user_len_sum[uid] / c)
            pipe.lpush(f"leaderboard:msg_lengths:{gid}:{uid}", avg)
        
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

async def main(target_guild_id: int, target_token: str):
    print("=" * 60)
    print(f"Discord Message History Backfill Script (FULL HISTORY)")
    print(f"Target Guild: {target_guild_id}")
    print("=" * 60)
    
    # Initialize bot
    intents = discord.Intents.default()
    intents.guilds = True
    intents.guild_messages = True # Fix: allow reading messages
    intents.members = True # Fix: allow reading member join dates
    
    bot = discord.Client(intents=intents)
    r = redis.from_url(REDIS_URL, decode_responses=True)
    
    @bot.event
    async def on_ready():
        print(f"\n✓ Logged in as {bot.user}")
        
        guild = bot.get_guild(target_guild_id)
        if not guild:
            print(f"ERROR: Could not find guild {target_guild_id}")
            # Try fetching if not in cache
            try:
                guild = await bot.fetch_guild(target_guild_id)
            except Exception as e:
                print(f"Fetch failed: {e}")
                await bot.close()
                return
        
        # 1. Reset Stats
        await reset_stats(r, target_guild_id)
        
        print(f"Guild: {guild.name}")
        print(f"Total text channels: {len(guild.text_channels) if hasattr(guild, 'text_channels') else 'Unknown'}\n")
        
        total_messages = 0
        
        # If fetch_guild was used, we might need to fetch channels explicitly
        channels = guild.text_channels if hasattr(guild, "text_channels") else []
        if not channels:
             # Try fetch channels
             try: channels = await guild.fetch_channels()
             except: pass
             channels = [c for c in channels if isinstance(c, discord.TextChannel)]

        for channel in channels:
            # Full History (days_back=None)
            count = await backfill_channel_history(bot, channel, r, days_back=None, current_total=total_messages)
            total_messages += count
        
        # --- NEW: Member Join Statistics (Traffic) ---
        print("\nProcessing Member Joins (Traffic)...")
        try:
             # Ensure we have members (requires intents.members)
             if not guild.members:
                 # Try chunking if zero (gateway issue)
                 await guild.chunk()
             
             join_counts = defaultdict(int) 
             # Format: YYYY-MM
             
             for member in guild.members:
                 if member.joined_at:
                     key = member.joined_at.strftime("%Y-%m")
                     join_counts[key] += 1
            
             if join_counts:
                 pipe = r.pipeline()
                 k_joins = f"stats:joins:{target_guild_id}"
                 for month, count in join_counts.items():
                     pipe.hincrby(k_joins, month, count)
                 await pipe.execute()
                 print(f"   ✓ Processed joins for {len(guild.members)} members over {len(join_counts)} months")
             else:
                 print("   ⚠️ No member join data found.")
                 
        except Exception as e:
            print(f"   ❌ Error processing member joins: {e}")

        # --- NEW: Mock/Init Command Stats from recent messages (Approximation) ---
        # Since we can't easily detect slash commands from history without interaction data, 
        # checking for '!' or '/' prefix in content is a weak but usable proxy for legacy commands.
        # Ideally, we rely on new data. But let's verify if we can do anything.
        # Skipping for now to avoid pollution with false positives.

        
        await report_progress(r, target_guild_id, "completed", total_messages)
        print("\n" + "=" * 60)
        print(f"✓ FULL Backfill complete!")
        print(f"  Total messages processed: {total_messages:,}")
        print("=" * 60)
        
        await r.close()
        await bot.close()
    
    try:
        await bot.start(target_token)
    except Exception as e:
        print(f"\n\nBackfill failed: {e}")
        await r.close()
        await bot.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--guild_id", type=int, help="Guild ID to backfill")
    parser.add_argument("--token", type=str, help="Bot Token (optional if in file)")
    args = parser.parse_args()
    
    # Load defaults
    def_token, def_gid = get_default_config()
    
    final_gid = args.guild_id or def_gid
    final_token = args.token or def_token
    
    if not final_gid:
        print("Error: Guild ID required. Use --guild_id or set in config.py")
        sys.exit(1)
        
    if not final_token:
        print("Error: Bot Token required. Use --token or set in bot_token.py")
        sys.exit(1)

    print("\n⚠️  This script will fetch ALL message history from Discord API.")
    print("   This may take a LONG time (hours depending on server size).")
    print("   Starting automatically in 2 seconds...\n")
    import time
    time.sleep(2)
    
    asyncio.run(main(final_gid, final_token))
