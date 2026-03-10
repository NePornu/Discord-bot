import asyncio
import json
import os
import sys

# Load environment variables
env_path = "/root/discord-bot/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val.strip('"').strip("'")

sys.path.append("/root/discord-bot")
from shared.python.redis_client import get_redis_client

GUILD_ID = 615171377783242769

async def check():
    r = await get_redis_client()
    key = f"automod:filters:{GUILD_ID}"
    val = await r.get(key)
    if not val:
        print("No filters found for guild", GUILD_ID)
    else:
        print(json.dumps(json.loads(val), indent=2))
    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
