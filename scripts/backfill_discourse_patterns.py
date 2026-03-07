#!/usr/bin/env python3
"""
Refined Discourse Backfill Script
Uses JSON for robust data extraction from the Discourse Postgres database.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from collections import defaultdict

import redis.asyncio as aioredis

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.pattern_logic import count_keywords, count_words
from shared.redis_client import REDIS_URL

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("DiscourseBackfill")

DISCOURSE_GID = 999 
PAT_TTL = 730 * 86400  # 2 years TTL

def run_psql_json(query):
    """Run a query and return JSON results."""
    # We wrap the query in json_agg to get a single JSON string back
    json_query = f"SELECT json_agg(t) FROM ({query}) t"
    cmd = f'docker exec app sudo -u postgres psql -d discourse -t -A -c "{json_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"PSQL Error: {result.stderr}")
        return []
    output = result.stdout.strip()
    if not output or output == "" or output == "null":
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON: {e}")
        return []

class DiscourseBackfiller:
    async def run(self, days=730):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        logger.info(f"Starting REFINED Discourse backfill ({days} days window)...")
        
        limit_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # 0. Identify non-staff users
        logger.info("Identifying non-staff Discourse users...")
        staff_query = "SELECT id FROM users WHERE admin = true OR moderator = true"
        staff_list = run_psql_json(staff_query)
        staff_ids = {s['id'] for s in staff_list} if staff_list else set()
        logger.info(f"Excluding {len(staff_ids)} staff members from Discourse.")

        # 1. Fetch posts
        query = f"""
        SELECT user_id, raw, created_at 
        FROM posts 
        WHERE created_at > '{limit_date}' 
        AND deleted_at IS NULL
        """
        posts = run_psql_json(query)
        if not posts:
            logger.warning("No posts found in the given window.")
        else:
            logger.info(f"Found {len(posts)} posts to analyze.")

        pipe = self.redis.pipeline()
        total_hits = 0
        processed_count = 0

        for p in posts:
            uid = p['user_id']
            if uid in staff_ids:
                continue
                
            text = p['raw']
            # Discourse timestamp: '2026-02-18T09:13:49.59158' (sometimes without timezone)
            ts_str = p['created_at'].replace('Z', '')
            if ' ' in ts_str: # Database format vs ISO
                ts_str = ts_str.replace(' ', 'T')
            
            # Remove microsecond part if it causes issues, or just handle it
            # Python 3.7+ fromisoformat can be picky
            try:
                if '.' in ts_str:
                    base, micros = ts_str.split('.')
                    # Truncate to 6 digits if longer
                    ts_str = f"{base}.{micros[:6]}"
                
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                # Fallback for simpler format
                ts = datetime.strptime(ts_str.split('.')[0], "%Y-%m-%dT%H:%M:%S")

            date_str = ts.strftime("%Y%m%d")
            hour = ts.hour

            wc = count_words(text)
            
            # Message stats
            msg_key = f"pat:msg:{DISCOURSE_GID}:{uid}:{date_str}"
            pipe.hincrby(msg_key, "word_count", wc)
            pipe.hincrby(msg_key, "msg_count", 1)
            pipe.expire(msg_key, PAT_TTL)

            # Hour stats
            hour_key = f"pat:hour:{DISCOURSE_GID}:{uid}:{date_str}"
            pipe.hincrby(hour_key, str(hour), 1)
            pipe.expire(hour_key, PAT_TTL)

            # Keyword scanning
            from shared.pattern_logic import KEYWORD_GROUPS
            for group in KEYWORD_GROUPS:
                hits = count_keywords(text, group)
                if hits > 0:
                    kw_key = f"pat:kw:{DISCOURSE_GID}:{uid}:{date_str}:{group}"
                    pipe.incrby(kw_key, hits)
                    pipe.expire(kw_key, PAT_TTL)
                    total_hits += hits

            processed_count += 1
            if len(pipe) > 500:
                await pipe.execute()
                pipe = self.redis.pipeline()

        await pipe.execute()
        
        # 2. Backfill user join dates
        logger.info("Backfilling join dates...")
        users = run_psql_json("SELECT id, created_at FROM users WHERE admin = false AND moderator = false")
        pipe = self.redis.pipeline()
        for u in users:
            uid = u['id']
            # Repeat parsing logic for join date
            ts_str = u['created_at'].replace('Z', '').replace(' ', 'T')
            try:
                if '.' in ts_str:
                    base, micros = ts_str.split('.')
                    ts_str = f"{base}.{micros[:6]}"
                ts_dt = datetime.fromisoformat(ts_str)
            except ValueError:
                ts_dt = datetime.strptime(ts_str.split('.')[0], "%Y-%m-%dT%H:%M:%S")
            
            ts_val = int(ts_dt.timestamp())
            join_key = f"pat:user_join:{DISCOURSE_GID}:{uid}"
            pipe.setnx(join_key, str(ts_val))
            pipe.expire(join_key, PAT_TTL)
        await pipe.execute()

        logger.info(f"Discourse backfill complete! Processed {processed_count} posts from non-staff, found {total_hits} keyword hits.")
        await self.redis.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=730)
    args = parser.parse_args()
    asyncio.run(DiscourseBackfiller().run(days=args.days))
