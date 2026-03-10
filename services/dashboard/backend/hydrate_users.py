
import asyncio
import redis.asyncio as redis
import sys
import httpx
import json
import sys

sys.path.append('/root/discord-bot')
from shared.redis_client import REDIS_URL
import os


try:
    with open('/root/discord-bot/.env', 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                
                v = v.strip('"').strip("'")
                os.environ[k] = v
except Exception as e:
    print(f"Warning parsing .env: {e}")


try:
    from config.dashboard_secrets import BOT_TOKEN
    if not BOT_TOKEN:
        BOT_TOKEN = os.getenv("BOT_TOKEN")
except ImportError:
    BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("Error: Could not import BOT_TOKEN. Please ensure config is set.")
    sys.exit(1)

async def hydrate_users():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    guild_id = 615171377783242769
    xp_key = f"levels:xp:{guild_id}"
    
    
    users = await r.zrevrange(xp_key, 0, -1)
    print(f"Checking {len(users)} users for missing info (High XP first)...")
    
    missing_count = 0
    updated_count = 0
    
    async with httpx.AsyncClient() as client:
        for uid in users:
            
            info = await r.hgetall(f"user:info:{uid}")
            if not info or not info.get("username"):
                missing_count += 1
                try:
                    
                    print(f"Fetching info for {uid}...", end="", flush=True)
                    resp = await client.get(
                        f"https://discord.com/api/v10/users/{uid}",
                        headers={"Authorization": f"Bot {BOT_TOKEN}"}
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        username = data["username"]
                        display = data.get("global_name") or username
                        avatar = data.get("avatar") or ""
                        
                        await r.hset(f"user:info:{uid}", mapping={
                            "username": display, 
                            "id": uid,
                            "avatar": avatar,
                            "discriminator": data.get("discriminator", "0")
                        })
                        print(f" OK ({display})")
                        updated_count += 1
                        await asyncio.sleep(0.5) 
                    elif resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", 2))
                        print(f" Rate Limited. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after + 0.1)
                        
                        
                    else:
                        print(f" Failed ({resp.status_code})")
                        await asyncio.sleep(0.2)
                        
                except Exception as e:
                    print(f" Error: {e}")
                    await asyncio.sleep(0.2)
                        
                except Exception as e:
                    print(f" Error: {e}")
            
    print(f"Hydration complete. Updated {updated_count} users. (Found {missing_count} missing)")

if __name__ == "__main__":
    asyncio.run(hydrate_users())
