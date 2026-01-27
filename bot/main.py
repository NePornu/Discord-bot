

from __future__ import annotations

import asyncio
import os
import time
import platform
import sys
from datetime import datetime

import discord

from discord.ext import commands, tasks 
from config import bot_token
from config import config
import redis.asyncio as redis 
from shared.redis_client import get_redis_client


def ts() -> str:
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=config.BOT_PREFIX, intents=intents)


bot.remove_command("help")

pending_console_msgs: list[str] = []

async def send_console_log(msg: str):
    """Pošli log do kanálu config.CONSOLE_CHANNEL_ID, nebo bufferuj do on_ready."""
    fullmsg = f"{ts()} {msg}"
    try:
        if not bot.is_ready():
            pending_console_msgs.append(fullmsg)
            print(f"[PENDING] {fullmsg}")
            return
        channel = bot.get_channel(config.CONSOLE_CHANNEL_ID)
        if channel:
            for i in range(0, len(fullmsg), 1900):
                await channel.send(f"```{fullmsg[i:i+1900]}```")
        else:
            print(f"[ERROR] Nelze najít console channel {config.CONSOLE_CHANNEL_ID}")
    except Exception as e:
        print(f"[ERROR] send_console_log failed: {e}")

async def log_start_info():
    await send_console_log("=== SPUŠTĚNÍ BOTA LOG ===")
    await send_console_log(f"Platforma: {platform.platform()} | Python: {sys.version.replace(chr(10), ' ')}")
    await send_console_log(f"discord.py: {discord.__version__}")
    await send_console_log(f"PID: {os.getpid()} | CWD: {os.getcwd()}")
    await send_console_log(f"Token v souboru: {'ANO' if hasattr(bot_token, 'TOKEN') else 'NE'}")
    await send_console_log(f"Prefix: {config.BOT_PREFIX!r}")
    await send_console_log(f"CONSOLE_CHANNEL_ID: {config.CONSOLE_CHANNEL_ID}")
    await send_console_log(f"'commands' existuje: {os.path.exists('commands')}")
    await send_console_log(f"Obsah 'commands': {os.listdir('commands') if os.path.exists('commands') else '—'}")

async def load_commands():
    start = time.time()
    is_lite = os.getenv("BOT_LITE_MODE") == "1"
    
    await send_console_log(f"START: načítání cogů (Lite Mode: {is_lite})…")
    
    commands_dir = os.path.join(os.path.dirname(__file__), "commands")
    if not os.path.exists(commands_dir):
        await send_console_log(f"[FATAL] složka '{commands_dir}' neexistuje")
        return

    
    if "help" in bot.all_commands:
        bot.remove_command("help")

    files = [
        f for f in os.listdir(commands_dir)
        if f.endswith(".py") and not f.startswith("_") and f != "__init__.py"
    ]
    await send_console_log(f"Celkem {len(files)} modulů: {files}")

    for filename in files:
        module_name = f"bot.commands.{filename[:-3]}"
        await send_console_log(f"Načítám: {module_name}")
        try:
            
            interactive_cogs = ["echo", "emojirole", "help", "log", "notify", "ping", "purge", "report", "verification", "vyzva", "analytics_tracking"]
            if is_lite and any(mod in module_name for mod in interactive_cogs):
                await send_console_log(f"⏩ {module_name} vynechán (Lite Mode)")
                continue

            await bot.load_extension(module_name)
            await send_console_log(f"✅ {module_name} načten")
        except Exception as e:
            import traceback
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1800:]
            await send_console_log(f"❌ Chyba při načtení {module_name}: {e}\n```{tb}```")
            continue

        
        try:
            mod = __import__(module_name, fromlist=['*'])
            classes = [attr for attr in dir(mod) if isinstance(getattr(mod, attr), type)]
            await send_console_log(f" - Třídy: {classes}")
        except Exception as e:
            await send_console_log(f" - Nelze vypsat třídy: {e}")

    await send_console_log(f"Načítání cogů hotovo za {time.time()-start:.2f}s")


@tasks.loop(seconds=10)
async def member_stats_task():
    """Periodically update the count of online members AND total members in Redis."""
    
    try:
        r = await get_redis_client()
        
        sys.stderr.write(f"{ts()} [DEBUG] MemberStatsTask: Checking {len(bot.guilds)} guilds (Ready: {bot.is_ready()})\n")
        
        for guild in bot.guilds:
            
            online_count = sum(
                1 for m in guild.members 
                if m.status != discord.Status.offline
            )
            
            
            total_members = guild.member_count
            
            sys.stderr.write(f"{ts()} [DEBUG] Guild {guild.id}: {total_members} total, {online_count} online\n")
            
            
            async with r.pipeline() as pipe:
                await pipe.setex(f"presence:online:{guild.id}", 60, str(online_count))
                await pipe.setex(f"presence:total:{guild.id}", 60, str(total_members))
                
                
                await pipe.set(f"guild:verification_level:{guild.id}", str(guild.verification_level.value))
                await pipe.set(f"guild:mfa_level:{guild.id}", str(int(guild.mfa_level)))  
                await pipe.set(f"guild:explicit_filter:{guild.id}", str(guild.explicit_content_filter.value))
                
                
                await pipe.sadd("bot:guilds", str(guild.id))
                
                
                
                
                
                
                await pipe.execute()
        
        await r.close()
    except Exception as e:
        print(f"Error in member_stats_task: {e}")

@member_stats_task.before_loop
async def before_member_stats_task():
    
    pass

@bot.event
async def on_ready():
    await send_console_log(f"Bot připojen: {bot.user} ({bot.user.id})")
    
    
    is_lite = os.getenv("BOT_LITE_MODE") == "1"
    status_msg = "Analytics 📈 stats.nepornu.cz" if is_lite else "nepornu.cz 📊"
    activity = discord.Activity(type=discord.ActivityType.watching, name=status_msg)
    await bot.change_presence(status=discord.Status.online, activity=activity)
    
    guilds = list(bot.guilds)
    await send_console_log(f"Členem {len(guilds)} serverů: {[g.name for g in guilds]}")

    
    try:
        r = redis.from_url(CONFIG["REDIS_URL"], decode_responses=True)
        
        idx_key = "bot:guilds:dashboard" if is_lite else "bot:guilds:primary"
        
        
        await r.delete(idx_key)
        
        
        if guilds:
            
            gids = [str(g.id) for g in guilds]
            await r.sadd(idx_key, *gids)
            
            await r.sadd("bot:guilds", *gids)
            
        await send_console_log(f"✅ Cache aktualizována ({idx_key}): {len(guilds)} serverů")
        await r.close()
    except Exception as e:
        await send_console_log(f"⚠️ Chyba cache: {e}")

    
    if pending_console_msgs:
        channel = bot.get_channel(config.CONSOLE_CHANNEL_ID)
        if channel:
            for msg in pending_console_msgs:
                for i in range(0, len(msg), 1900):
                    await channel.send(f"```{msg[i:i+1900]}```")
        pending_console_msgs.clear()

    await send_console_log("Načítám cogy…")
    await load_commands()

    
    
    try:
        pass
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
            
        
        
        

    except Exception as e:
        await send_console_log(f"❌ Sync selhal: {e}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    await send_console_log(f"🆕 PŘIPOJEN NA GUIDLU: {guild.name} ({guild.id})")
    
    
    token = getattr(bot_token, "TOKEN", None)
    if token:
        import subprocess
        import sys
        try:
            import os
            
            script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "backfill_stats.py"))
            cmd = [sys.executable, script_path, "--guild_id", str(guild.id), "--token", token]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await send_console_log(f"⏳ Spuštěn auto-backfill pro {guild.name}")
        except Exception as e:
            await send_console_log(f"❌ Auto-backfill selhal: {e}")

    
    try:
        r = redis.from_url(CONFIG["REDIS_URL"], decode_responses=True)
        is_lite = os.getenv("BOT_LITE_MODE") == "1"
        idx_key = "bot:guilds:dashboard" if is_lite else "bot:guilds:primary"
        
        await r.sadd(idx_key, str(guild.id))
        await r.sadd("bot:guilds", str(guild.id))
        await r.close()
    except Exception as e:
        print(f"Redis add error: {e}")

    await send_console_log("✅ Start dokončen, bot připraven.")
    
    
    if not member_stats_task.is_running():
        member_stats_task.start()
        print("✅ Background task: Member stats sync started")

@bot.event
async def on_guild_remove(guild: discord.Guild):
    await send_console_log(f"👋 ODPOJEN ZE SERVERU: {guild.name} ({guild.id})")
    
    try:
        r = redis.from_url(CONFIG["REDIS_URL"], decode_responses=True)
        is_lite = os.getenv("BOT_LITE_MODE") == "1"
        idx_key = "bot:guilds:dashboard" if is_lite else "bot:guilds:primary"
        
        await r.srem(idx_key, str(guild.id))
        
        
        await r.srem("bot:guilds", str(guild.id)) 
        
        await r.close()
    except Exception as e:
        print(f"Redis remove error: {e}")































        

    









    



    








@bot.check
async def globally_block_commands(ctx: commands.Context):
    
    if ctx.command is None:
        return True
    command_name = ctx.command.name
    command_config = config.COMMANDS_CONFIG.get(command_name, {})
    await send_console_log(f"Globální check: {command_name} | {ctx.author} ({ctx.author.id})")
    if not command_config.get("enabled", False):
        await send_console_log(f"Příkaz {command_name} je v konfiguraci vypnut")
        return False
    if command_config.get("admin_only", False) and not getattr(ctx.author.guild_permissions, "administrator", False):
        await send_console_log(f"{ctx.author} se pokusil o admin-only příkaz {command_name}")
        return False
    return True

async def main():
    await log_start_info()
    await send_console_log("Inicializace…")
    
    token = os.getenv("BOT_TOKEN") or getattr(bot_token, "TOKEN", None)
    
    if not token or len(token) < 30:
        await send_console_log("[FATAL] Chybí validní bot token")
        print(ts(), "[FATAL] Chybí validní bot token")
        return
    await send_console_log("Token OK, startuji…")
    
    
    if not member_stats_task.is_running():
        member_stats_task.start()
        print(ts(), "✅ Background task: Member stats sync started (from main)")
    
    
    
    await bot.start(token)

if __name__ == "__main__":
    try:
        print(ts(), "[DEBUG] Spouštění bota…")
        asyncio.run(main())
    except Exception as e:
        print(ts(), f"[ERROR] Chyba při spuštění bota: {e}")
