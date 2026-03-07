#!/usr/bin/env python3
"""
Backfill Patterns Script
Fetches historical messages from Discord channels and populates Redis with pattern signals
(keyword hits, word counts, etc.) for the Pattern Detection Engine.
"""

import asyncio
import argparse
import os
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import discord
import redis.asyncio as aioredis

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.pattern_logic import count_keywords, count_words
from shared.redis_client import REDIS_URL

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("BackfillPatterns")

# Define redis helpers locally to avoid dependency on Cog instance
def K_KW(gid, uid, date, group):  return f"pat:kw:{gid}:{uid}:{date}:{group}"
def K_MSG(gid, uid, date):        return f"pat:msg:{gid}:{uid}:{date}"
def K_FIRST(gid, uid):            return f"pat:first_msg:{gid}:{uid}"
def K_JOIN(gid, uid):             return f"pat:user_join:{gid}:{uid}"
def K_HOUR(gid, uid, date):       return f"pat:hour:{gid}:{uid}:{date}"

PAT_TTL = 730 * 86400  # 2 years TTL

class BackfillPatternsClient(discord.Client):
    def __init__(self, guild_id, days, token):
        intents = discord.Intents.all()
        super().__init__(intents=intents)
        self.target_guild_id = guild_id
        self.days = days
        self.token = token
        self.redis = None

    async def setup_redis(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Starting pattern backfill for guild {self.target_guild_id} ({self.days} days)...")
        
        try:
            await self.setup_redis()
            guild = self.get_guild(self.target_guild_id)
            if not guild:
                logger.error(f"Guild {self.target_guild_id} not found!")
                await self.close()
                return

            await self.run_backfill(guild)
        except Exception as e:
            logger.error(f"Error during backfill: {e}", exc_info=True)
        finally:
            if self.redis:
                await self.redis.close()
            await self.close()

    async def run_backfill(self, guild):
        gid = guild.id
        limit_date = datetime.now(timezone.utc) - timedelta(days=self.days)
        
        # 0. Identify active non-staff members
        logger.info("Identifying active non-staff members...")
        staff_keywords = {
            "mentor", "moderátor", "admin", "průvodce", "tým", "koordinátor", 
            "pracovník", "vedení", "kouč", "lektor", "expert", "specialista", "správce"
        }
        
        active_member_ids = set()
        for member in guild.members:
            if member.bot: continue
            
            is_staff = member.guild_permissions.administrator or \
                       any(any(kw in r.name.lower() for kw in staff_keywords) for r in member.roles)
            
            if not is_staff:
                active_member_ids.add(member.id)
        
        logger.info(f"Filtered to {len(active_member_ids)} active non-staff users.")

        # 1. Prepare channels
        channels = [c for c in guild.text_channels if c.permissions_for(guild.me).read_message_history]
        diary_keywords = ["denik", "deník", "diary"]
        channels.sort(key=lambda c: any(k in c.name.lower() for k in diary_keywords), reverse=True)
        
        logger.info(f"Scanning {len(channels)} text channels since {limit_date.date()}...")

        total_msgs = 0
        total_hits = 0

        buffer = defaultdict(int) 
        msg_stats_buffer = defaultdict(lambda: {"wc": 0, "cc": 0, "mc": 0, "rc": 0, "mt": 0})
        first_msg_buffer = {}

        for idx, channel in enumerate(channels):
            chan_msgs = 0
            logger.info(f"[{idx+1}/{len(channels)}] Scanning #{channel.name}...")
            
            try:
                async for msg in channel.history(limit=None, after=limit_date, oldest_first=True):
                    if msg.author.bot or msg.author.id not in active_member_ids:
                        continue
                    
                    uid = msg.author.id
                    date_str = msg.created_at.strftime("%Y%m%d")
                    text = msg.content or ""
                    
                    # Update message stats
                    s = msg_stats_buffer[(uid, date_str)]
                    wc = count_words(text)
                    s["wc"] += wc
                    s["cc"] += len(text)
                    s["mc"] += 1
                    if msg.reference: s["rc"] += 1
                    if msg.mentions: s["mt"] += len(msg.mentions)

                    # Update hourly distribution
                    hour = msg.created_at.hour
                    buffer[(uid, date_str, "hour", str(hour))] += 1

                    # Update first message
                    if uid not in first_msg_buffer:
                        first_msg_buffer[uid] = {
                            "msg_id": str(msg.id),
                            "timestamp": str(int(msg.created_at.timestamp())),
                            "channel_id": str(channel.id)
                        }

                    # Keyword scanning
                    from shared.pattern_logic import KEYWORD_GROUPS
                    for group in KEYWORD_GROUPS:
                        hits = count_keywords(text, group)
                        if hits > 0:
                            buffer[(uid, date_str, "kw", group)] += hits
                            total_hits += hits

                    chan_msgs += 1
                    total_msgs += 1

                    if total_msgs % 1000 == 0:
                        logger.info(f"  ... {total_msgs} messages scanned ...")
                        await self.flush_to_redis(gid, buffer, msg_stats_buffer, first_msg_buffer)

            except discord.Forbidden:
                logger.warning(f"  Access forbidden to #{channel.name}")
            except Exception as e:
                logger.error(f"  Error in #{channel.name}: {e}")

            logger.info(f"  Done #{channel.name}: {chan_msgs} messages.")

        # Final flush
        await self.flush_to_redis(gid, buffer, msg_stats_buffer, first_msg_buffer)
        
        # Backfill join dates for current members
        logger.info("Backfilling member join dates...")
        pipe = self.redis.pipeline()
        for member in guild.members:
            if member.bot: continue
            if member.joined_at:
                pipe.setnx(K_JOIN(gid, member.id), str(int(member.joined_at.timestamp())))
                pipe.expire(K_JOIN(gid, member.id), PAT_TTL)
        await pipe.execute()

        logger.info(f"Backfill complete! Scanned {total_msgs} messages, found {total_hits} keyword hits.")

    async def flush_to_redis(self, gid, buffer, stats, first_msgs):
        if not buffer and not stats and not first_msgs:
            return
            
        pipe = self.redis.pipeline()
        
        # Flush keyword hits and hourly counts
        for (uid, date, btype, subtype), count in buffer.items():
            if btype == "kw":
                key = K_KW(gid, uid, date, subtype)
                pipe.incrby(key, count)
                pipe.expire(key, PAT_TTL)
            elif btype == "hour":
                key = K_HOUR(gid, uid, date)
                pipe.hincrby(key, subtype, count)
                pipe.expire(key, PAT_TTL)
        buffer.clear()

        # Flush message stats
        for (uid, date), s in stats.items():
            key = K_MSG(gid, uid, date)
            pipe.hincrby(key, "word_count", s["wc"])
            pipe.hincrby(key, "msg_count", s["mc"])
            pipe.hincrby(key, "char_count", s["cc"])
            pipe.hincrby(key, "reply_count", s["rc"])
            pipe.hincrby(key, "mention_count", s["mt"])
            pipe.expire(key, PAT_TTL)
        stats.clear()

        # Flush first messages
        for uid, data in first_msgs.items():
            # Only set if not exists (oldest first logic)
            key = K_FIRST(gid, uid)
            pipe.hsetnx(key, "msg_id", data["msg_id"])
            pipe.hsetnx(key, "timestamp", data["timestamp"])
            pipe.hsetnx(key, "channel_id", data["channel_id"])
            pipe.expire(key, PAT_TTL)
        first_msgs.clear()

        await pipe.execute()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--guild_id", type=int, required=True)
    parser.add_argument("--token", type=str, required=True)
    parser.add_argument("--days", type=int, default=730)
    args = parser.parse_args()

    client = BackfillPatternsClient(args.guild_id, args.days, args.token)
    try:
        client.run(args.token)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
