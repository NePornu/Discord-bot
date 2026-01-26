import asyncio
from shared.redis_client import get_redis

async def check():
    r = await get_redis()
    bot_guilds = await r.smembers("bot:guilds")
    print(f"Bot Guilds in Redis: {bot_guilds}")
    
    for gid in bot_guilds:
        tm = await r.get(f"stats:total_msgs:{gid}")
        lb_size = await r.zcard(f"leaderboard:messages:{gid}")
        print(f"Guild {gid}: Total Msgs={tm}, Leaderboard size={lb_size}")
        
    await r.close()

if __name__ == "__main__":
    asyncio.run(check())
