import asyncio
import logging
import discord
import os
import sys

# Add project roots to path
sys.path.append("/app")

from shared.python.redis_client import get_redis_client
from shared.python.config import config
from services.worker.commands.patterns import PatternDetectorCog
from services.worker.commands.patterns.common import K_THREAD, K_THREAD_UID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RefreshScript")

async def run_refresh():
    # 1. Setup Discord Client
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = discord.Client(intents=intents)
    
    # We don't need to run full bot, just enough to fetch channels
    await bot.login(os.getenv("BOT_TOKEN"))
    
    r = await get_redis_client()
    try:
        gid = config.GUILD_ID
        logger.info(f"Scanning for active threads in guild {gid}...")
        
        # 2. Get all thread keys
        cursor = "0"
        threads_to_refresh = []
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=f"pat:thread:{gid}:*", count=1000)
            for k in keys:
                uid = k.split(":")[-1]
                tid = await r.get(k)
                if tid:
                    threads_to_refresh.append((int(uid), int(tid)))
            if cursor == 0 or cursor == "0": break
            
        logger.info(f"Found {len(threads_to_refresh)} threads to refresh.")

        # 3. Setup Pattern Detector for building embeds
        # We need a dummy cog/bot setup
        from services.worker.commands.patterns.detectors import PatternDetectors
        from services.worker.commands.patterns.alerts import ModeratorAssistantView
        detectors = PatternDetectors(gid)
        
        for uid, tid in threads_to_refresh:
            try:
                thread = await bot.fetch_channel(tid)
                if not thread: continue
                
                logger.info(f"Refreshing thread {tid} for user {uid}...")
                
                # Fetch member info
                user_mention = f"<@{uid}>"
                display_name = f"Uživatel {uid}"
                avatar_url = None
                
                try:
                    member = thread.guild.get_member(uid) or await thread.guild.fetch_member(uid)
                    if member:
                        display_name = member.display_name
                        user_mention = member.mention
                        avatar_url = member.display_avatar.url
                except: pass

                # Build new embed
                embed = await detectors.build_diagnostic_embed(r, uid, user_mention, display_name, avatar_url)
                view = ModeratorAssistantView(uid, gid)
                
                # Find the diagnostic message
                found = False
                
                # Check for various titles
                search_titles = ["Karta klienta", "Detekce vzorců", "Hloubková analýza"]

                # 1. Check parent message (if thread is attached to a msg)
                try:
                    parent_id = thread.id
                    parent_channel = thread.parent or await bot.fetch_channel(thread.parent_id)
                    parent_msg = await parent_channel.fetch_message(parent_id)
                    if parent_msg and parent_msg.author.id == bot.user.id and parent_msg.embeds:
                         match = any(st in (parent_msg.embeds[0].title or "") for st in search_titles)
                         if match:
                            await parent_msg.edit(embed=embed, view=view)
                            logger.info(f"Updated parent message {parent_id} for thread {tid}")
                            found = True
                except Exception as e:
                    logger.debug(f"Parent msg not found for {tid}: {e}")

                # 2. Check starter message (for forum posts/independent threads)
                if not found:
                    try:
                        starter = await thread.fetch_message(thread.id)
                        if starter and starter.author.id == bot.user.id and starter.embeds:
                            match = any(st in (starter.embeds[0].title or "") for st in search_titles)
                            if match:
                                await starter.edit(embed=embed, view=view)
                                logger.info(f"Updated starter message in thread {tid}")
                                found = True
                    except: pass

                # 3. Check history inside thread
                if not found:
                    async for msg in thread.history(limit=20):
                        if msg.author.id == bot.user.id and msg.embeds:
                            match = any(st in (msg.embeds[0].title or "") for st in search_titles)
                            if match:
                                await msg.edit(embed=embed, view=view)
                                logger.info(f"Updated history msg in thread {tid}")
                                found = True
                                break
                            
                if not found:
                    logger.warning(f"Could not find diagnostic embed in thread {tid}")
                    # Optionally post a new one? No, user only asked to update.
                    
            except Exception as e:
                logger.error(f"Failed to refresh thread {tid}: {e}")

    finally:
        await r.aclose()
        await bot.close()

if __name__ == "__main__":
    asyncio.run(run_refresh())
