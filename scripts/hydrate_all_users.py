#!/usr/bin/env python3
"""
Hydrate user info for ALL users with events data.
"""
import asyncio
import redis.asyncio as redis
import httpx
import os
import sys

sys.path.append('/root/discord-bot')

# Load .env
try:
    with open('/root/discord-bot/.env', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                v = v.strip('"').strip("'")
                os.environ[k] = v
except Exception as e:
    print(f"Warning parsing .env: {e}")

REDIS_URL = os.getenv("REDIS_URL", "redis://172.22.0.2:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("Error: BOT_TOKEN not set")
    sys.exit(1)

async def hydrate_all_users():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    guild_id = 615171377783242769
    
    # Collect all user IDs from events:msg keys
    users = set()
    async for key in r.scan_iter(f"events:msg:{guild_id}:*"):
        uid = key.split(":")[-1]
        users.add(uid)
    
    print(f"Found {len(users)} users with message events")
    
    missing = []
    for uid in users:
        info = await r.hgetall(f"user:info:{uid}")
        # Check if name is missing or is just "User {id}"
        name = info.get("name") or info.get("username") or ""
        if not name or name.startswith("User "):
            missing.append(uid)
    
    print(f"Need to fetch info for {len(missing)} users")
    
    updated = 0
    async with httpx.AsyncClient() as client:
        for i, uid in enumerate(missing):
            try:
                print(f"[{i+1}/{len(missing)}] Fetching {uid}...", end="", flush=True)
                resp = await client.get(
                    f"https://discord.com/api/v10/users/{uid}",
                    headers={"Authorization": f"Bot {BOT_TOKEN}"}
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    display = data.get("global_name") or data["username"]
                    avatar_hash = data.get("avatar") or ""
                    # Build full avatar URL
                    avatar_url = ""
                    if avatar_hash:
                        ext = "gif" if avatar_hash.startswith("a_") else "png"
                        avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.{ext}?size=128"
                    
                    await r.hset(f"user:info:{uid}", mapping={
                        "name": display,
                        "username": data["username"],
                        "avatar": avatar_url,
                        "roles": ""  # Can't get roles via user API
                    })
                    await r.expire(f"user:info:{uid}", 7 * 86400)
                    print(f" ✓ {display}")
                    updated += 1
                    await asyncio.sleep(0.3)
                    
                elif resp.status_code == 429:
                    retry = float(resp.headers.get("Retry-After", 2))
                    print(f" Rate limited, waiting {retry}s...")
                    await asyncio.sleep(retry + 0.1)
                    # Retry this user
                    missing.append(uid)
                else:
                    print(f" ✗ HTTP {resp.status_code}")
                    await asyncio.sleep(0.2)
                    
            except Exception as e:
                print(f" Error: {e}")
                await asyncio.sleep(0.2)
    
    print(f"\n✓ Done! Updated {updated} users.")
    await r.close()

if __name__ == "__main__":
    asyncio.run(hydrate_all_users())
