
import discord
import asyncio
import redis.asyncio as redis
from config import GUILD_ID
try:
    from bot_token import TOKEN
except ImportError:
    from config import TOKEN

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

client = discord.Client(intents=intents)

from discord.http import Route

async def refresh_names():
    await client.wait_until_ready()
    print(f"Logged in as {client.user}")
    
    guild_id = int(GUILD_ID)
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    pipe = r.pipeline()
    count = 0

    print("Fetching ALL channels via Raw API...")
    try:
        
        
        channels_data = await client.http.request(Route('GET', '/guilds/{guild_id}/channels', guild_id=guild_id))
        print(f"Raw API returned {len(channels_data)} channels.")
        
        for c in channels_data:
            c_id = c['id']
            c_name = c.get('name', f"Channel {c_id}")
            
            pipe.hset(f"channel:info:{c_id}", mapping={"name": c_name})
            count += 1
            
        
        
        threads_data = await client.http.request(Route('GET', '/guilds/{guild_id}/threads/active', guild_id=guild_id))
        
        active_threads = threads_data.get('threads', [])
        print(f"Raw API returned {len(active_threads)} active threads.")
        
        for t in active_threads:
            t_id = t['id']
            t_name = t.get('name', f"Thread {t_id}")
            pipe.hset(f"channel:info:{t_id}", mapping={"name": t_name})
            count += 1
            
        
        
        print("Fetching Archived Threads (this might take a while)...")
        target_types = [0, 5, 15] 
        parent_ids = [c['id'] for c in channels_data if c['type'] in target_types]
        
        for pid in parent_ids:
            try:
                
                
                archived_data = await client.http.request(Route('GET', '/channels/{channel_id}/threads/archived/public', channel_id=pid))
                threads = archived_data.get('threads', [])
                if threads:
                    print(f"Found {len(threads)} archived threads in parent {pid}")
                    for t in threads:
                        t_id = t['id']
                        t_name = t.get('name', f"Archived Thread {t_id}")
                        pipe.hset(f"channel:info:{t_id}", mapping={"name": t_name})
                        count += 1
            except Exception as e:
                
                
                
                pass
            
            
            await asyncio.sleep(0.1)
            
    except Exception as e:
        print(f"HTTPErr: {e}")

    
    
    
    
    
    print("Caching members from lib cache...")
    guild = client.get_guild(guild_id)
    if guild:
        for member in guild.members:
             real_name = f"{member.name}#{member.discriminator}"
             pipe.hset(f"user:info:{member.id}", mapping={"name": real_name, "avatar": str(member.avatar_url or "")})
             count += 1
    
    await pipe.execute()
    await r.close()
    
    print(f"✅ Updated {count} entities in Redis.")
    await client.close()

client.loop.create_task(refresh_names())
client.run(TOKEN)
