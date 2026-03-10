

from __future__ import annotations

import asyncio
import os
import time
import platform
import sys
from datetime import datetime
import os

# Manual .env loading
# Manual .env loading (trying multiple paths for local vs container)
env_paths = [
    os.path.join(os.getcwd(), ".env"),
    "/app/.env",
    "/root/discord-bot/.env"
]
for env_path in env_paths:
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    # Don't overwrite existing environment variables (respect run.sh overrides)
                    if key not in os.environ:
                        os.environ[key] = val.strip('"').strip("'")
        break

import discord

from discord.ext import commands, tasks 
from shared.python.config import config
import redis.asyncio as redis 
from shared.python.redis_client import get_redis_client


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
        print(f"[lOG] {fullmsg}")
        if channel:
            for i in range(0, len(fullmsg), 1900):
                await channel.send(f"```{fullmsg[i:i+1900]}```")
        else:
            print(f"[ERROR] Nelze najít console channel {config.CONSOLE_CHANNEL_ID}")
    except Exception as e:
        print(f"[ERROR] send_console_log failed: {e}")

async def log_start_info():
    print("=== SPUŠTĚNÍ BOTA LOG ===")
    print(f"Platforma: {platform.platform()} | Python: {sys.version.replace(chr(10), ' ')}")
    print(f"discord.py: {discord.__version__}")
    print(f"PID: {os.getpid()} | CWD: {os.getcwd()}")
    print(f"Token v souboru: {'ANO' if config.BOT_TOKEN else 'NE'}")
    print(f"Prefix: {config.BOT_PREFIX!r}")
    print(f"CONSOLE_CHANNEL_ID: {config.CONSOLE_CHANNEL_ID}")
    commands_path = os.path.join(os.path.dirname(__file__), "commands")
    print(f"'commands' existuje: {os.path.exists(commands_path)}")
    print(f"Obsah 'commands': {os.listdir(commands_path) if os.path.exists(commands_path) else '—'}")

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_tree(ctx: commands.Context, scope: str = "guild"):
    """
    Synchronizace slash příkazů.
    Použití: !sync (pro tento server) | !sync global (globálně)
    """
    if scope == "global":
        await ctx.send("⏳ Synchronizuji slash příkazy GLOBÁLNĚ (může přepsat Go-core příkazy)...")
        try:
            synced = await bot.tree.sync()
            await ctx.send(f"✅ Globálně synchronizováno {len(synced)} příkazů.")
        except Exception as e:
            await ctx.send(f"❌ Chyba při globální synchronizaci: {e}")
    else:
        await ctx.send("⏳ Synchronizuji slash příkazy pro TENTO SERVER...")
        try:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced = await bot.tree.sync(guild=ctx.guild)
            await ctx.send(f"✅ Synchronizováno {len(synced)} příkazů pro tento server.")
        except Exception as e:
            await ctx.send(f"❌ Chyba při synchronizaci na serveru: {e}")

async def load_commands():
    start = time.time()
    await send_console_log("START: načítání cogů (Python Worker)…")
    
    commands_dir = os.path.join(os.path.dirname(__file__), "commands")
    if not os.path.exists(commands_dir):
        await send_console_log(f"[FATAL] složka '{commands_dir}' neexistuje")
        return []

    loaded_cogs = []
    for filename in os.listdir(commands_dir):
        if filename.endswith(".py") and not filename.startswith("_") and filename != "__init__.py":
            module_name = f"services.worker.commands.{filename[:-3]}"

            await send_console_log(f"Načítám: {module_name}")
            try:
                await bot.load_extension(module_name)
                await send_console_log(f"✅ {module_name} načten")
                loaded_cogs.append(filename[:-3])
            except Exception as e:
                import traceback
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1800:]
                await send_console_log(f"❌ Chyba při načtení {module_name}: {e}\n```{tb}```")
                global pending_console_msgs
                pending_console_msgs.append(f"❌ Chyba při načtení {module_name}: {e}")
                continue

    await send_console_log(f"Načítání cogů hotovo za {time.time()-start:.2f}s")
    return loaded_cogs

# Background tasks logic migrated to Go Core. 
# Empty loops kept as placeholders to avoid breaking refresh logic if referenced.
@tasks.loop(seconds=60)
async def member_stats_task():
    pass

@member_stats_task.before_loop
async def before_member_stats_task():
    pass

async def acquire_instance_lock(r: redis.Redis, is_lite: bool) -> bool:
    """Attempts to acquire a unique lock for this bot instance type in Redis."""
    lock_key = f"bot:lock:{'lite' if is_lite else 'primary'}"
    # Try to set the lock with a 60 second TTL
    success = await r.set(lock_key, str(os.getpid()), ex=60, nx=True)
    return bool(success)

@tasks.loop(seconds=10)
async def refresh_instance_lock_task():
    """Periodically refreshes the instance lock TTL with higher frequency and buffer."""
    is_lite = os.getenv("BOT_LITE_MODE", "0") == "1"
    lock_key = f"bot:lock:{'lite' if is_lite else 'primary'}"
    my_pid = str(os.getpid())
    r = None
    try:
        r = await get_redis_client()
        val = await r.get(lock_key)
        
        if val == my_pid:
            # We own it, refresh with 2 minute TTL for safety
            await r.expire(lock_key, 120)
        elif val is None:
            # Lock expired but nobody else took it - reclaim it
            success = await r.set(lock_key, my_pid, ex=120, nx=True)
            if success:
                print(f"[{ts()}] [INFO] Instance lock {lock_key} was silently re-acquired.")
            else:
                # Beaten in a race condition
                await send_console_log(f"⚠️ [CRITICAL] Instance lock {lock_key} stolen during re-acquisition!")
        else:
            # Someone else actually has it
            await send_console_log(f"⚠️ [CRITICAL] Instance lock {lock_key} is held by another process (PID: {val})!")
    except Exception as e:
        print(f"[{ts()}] [ERROR] Lock refresh failed: {e}")
    finally:
        if r:
            await r.aclose()


@member_stats_task.before_loop
async def before_member_stats_task():
    pass

@tasks.loop(seconds=60)
async def heartbeat_task():
    """Updates a heartbeat key in Redis to show the bot is alive."""
    r = None
    try:
        r = await get_redis_client()
        await r.set("bot:heartbeat", str(time.time()))
    except Exception as e:
        print(f"[{ts()}] [ERROR] Heartbeat failed: {e}")
    finally:
        if r:
            await r.aclose()

@heartbeat_task.before_loop
async def before_heartbeat_task():
    pass

@bot.event
async def on_ready():
    import platform
    import sys
    await send_console_log("=== PYTHON WORKER SPUŠTĚN ===")
    await send_console_log(f"Platforma: {platform.platform()} | Python: {sys.version.split(' ')[0]}")
    await send_console_log(f"PID: {os.getpid()} | CWD: {os.getcwd()}")
    
    loaded_cogs = await load_commands()
    await send_console_log(f"Bot připojen: {bot.user} ({bot.user.id})")
    
    # Status updated in Go Core
    
    guilds = list(bot.guilds)
    await send_console_log(f"Členem {len(guilds)} serverů: {[g.name for g in guilds]}")

    r = None
    try:
        r = redis.from_url(config.REDIS_URL, decode_responses=True)
        idx_key = "bot:guilds:worker"
        await r.delete(idx_key)
        if guilds:
            gids = [str(g.id) for g in guilds]
            await r.sadd(idx_key, *gids)
            await r.sadd("bot:guilds", *gids)
        await send_console_log(f"✅ Cache aktualizována ({idx_key}): {len(guilds)} serverů")
    except Exception as e:
        await send_console_log(f"⚠️ Chyba cache: {e}")
    finally:
        if r:
            await r.aclose()

    global pending_console_msgs
    errors = [m for m in pending_console_msgs if "FATAL" in m or "ERROR" in m or "Chyba" in m]
    pending_console_msgs.clear()
    
    for err in errors:
        await send_console_log(err)


    # await send_console_log("Načítám cogy…")
    # await send_console_log("Načítám cogy…")
    # await load_commands()

    
    
    # Automatic global sync removed to prevent conflicts with Go-core commands.
    # Use !sync command manually if needed.
    pass


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    try:
        import discord.app_commands as app_errors
        if isinstance(error, app_errors.errors.CommandNotFound):
            return # Be silent, might be handled by Go-core
        # log other app command errors
        await send_console_log(f"⚠️ App command error: {error}")
    except Exception as e:
        print(f"Error in on_app_command_error handler: {e}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    await send_console_log(f"🆕 PŘIPOJEN NA GUIDLU: {guild.name} ({guild.id})")
    
    
    token = config.BOT_TOKEN
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

    r = None
    try:
        r = redis.from_url(config.REDIS_URL, decode_responses=True)
        idx_key = "bot:guilds:worker"
        
        await r.sadd(idx_key, str(guild.id))
        await r.sadd("bot:guilds", str(guild.id))
    except Exception as e:
        print(f"Redis add error: {e}")
    finally:
        if r:
            await r.aclose()

    await send_console_log("✅ Start dokončen, bot připraven.")

@bot.event
async def on_guild_remove(guild: discord.Guild):
    await send_console_log(f"👋 ODPOJEN ZE SERVERU: {guild.name} ({guild.id})")
    
    r = None
    try:
        r = redis.from_url(config.REDIS_URL, decode_responses=True)
        idx_key = "bot:guilds:worker"
        
        await r.srem(idx_key, str(guild.id))
        
        
        await r.srem("bot:guilds", str(guild.id)) 
        
    except Exception as e:
        print(f"Redis remove error: {e}")
    finally:
        if r:
            await r.aclose()































        

    









    



    









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
    
    import os
    token = config.BOT_TOKEN
    if not token or len(token) < 30:
        await send_console_log("[FATAL] Chybí validní bot token")
        print(ts(), "[FATAL] Chybí validní bot token")
        return
    await send_console_log("Token OK, startuji…")
    
    import os
    is_lite = os.getenv("BOT_LITE_MODE", "0") == "1"
    
    # Instance Locking
    r_lock = await get_redis_client()
    if not await acquire_instance_lock(r_lock, is_lite):
        print(f"❌ [ERROR] Instance lock is already taken! (Lite: {is_lite})")
        await r_lock.aclose()
        return
    await r_lock.aclose()
    
    refresh_instance_lock_task.start()
    print(ts(), "✅ Instance lock acquired (Worker)")

    await bot.start(token)


if __name__ == "__main__":
    try:
        print(ts(), "[DEBUG] Spouštění bota…")
        asyncio.run(main())
    except Exception as e:
        print(ts(), f"[ERROR] Chyba při spuštění bota: {e}")
