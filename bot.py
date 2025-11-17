# bot.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import time
import platform
import sys
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
import bot_token
import config

# ---------- util ----------
def ts() -> str:
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=config.BOT_PREFIX, intents=intents)

# Odeber vestavěný help IHNED – předejde kolizi s naším /help z cogů
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
    await send_console_log("START: načítání cogů…")
    if not os.path.exists("commands"):
        await send_console_log("[FATAL] složka 'commands' neexistuje")
        return

    # safety – kdyby něco zaregistrovalo 'help' předem (hot-reload apod.)
    if "help" in bot.all_commands:
        bot.remove_command("help")

    files = [
        f for f in os.listdir("commands")
        if f.endswith(".py") and not f.startswith("_") and f != "__init__.py"
    ]
    await send_console_log(f"Celkem {len(files)} modulů: {files}")

    for filename in files:
        module_name = f"commands.{filename[:-3]}"
        await send_console_log(f"Načítám: {module_name}")
        try:
            await bot.load_extension(module_name)
            await send_console_log(f"✅ {module_name} načten")
        except Exception as e:
            import traceback
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1800:]
            await send_console_log(f"❌ Chyba při načtení {module_name}: {e}\n```{tb}```")
            continue

        # debug třídy (nevadí když selže)
        try:
            mod = __import__(module_name, fromlist=['*'])
            classes = [attr for attr in dir(mod) if isinstance(getattr(mod, attr), type)]
            await send_console_log(f" - Třídy: {classes}")
        except Exception as e:
            await send_console_log(f" - Nelze vypsat třídy: {e}")

    await send_console_log(f"Načítání cogů hotovo za {time.time()-start:.2f}s")

@bot.event
async def on_ready():
    await send_console_log(f"Bot připojen: {bot.user} ({bot.user.id})")
    guilds = list(bot.guilds)
    await send_console_log(f"Členem {len(guilds)} serverů: {[g.name for g in guilds]}")

    # odešli buffered logy (zachovej chunkování)
    if pending_console_msgs:
        channel = bot.get_channel(config.CONSOLE_CHANNEL_ID)
        if channel:
            for msg in pending_console_msgs:
                for i in range(0, len(msg), 1900):
                    await channel.send(f"```{msg[i:i+1900]}```")
        pending_console_msgs.clear()

    await send_console_log("Načítám cogy…")
    await load_commands()

    # === FIX: per-guild sync musí nejdřív zkopírovat globální příkazy ===
    try:
        gid = int(getattr(config, "GUILD_ID", 0) or 0)
        if gid > 0:
            gobj = discord.Object(id=gid)
            # Překopíruj všechny globální app příkazy (včetně hybrid) do guild command setu
            bot.tree.copy_global_to(guild=gobj)
            synced = await bot.tree.sync(guild=gobj)
            await send_console_log(f"✅ Slash příkazy syncnuty pro guild {gid}: {len(synced)}")
        else:
            synced = await bot.tree.sync()
            await send_console_log(f"✅ Slash příkazy syncnuty globálně: {len(synced)}")
    except Exception as e:
        await send_console_log(f"❌ Sync selhal: {e}")

    await send_console_log("✅ Start dokončen, bot připraven.")

# ---- /sync (admin only) ----
def _is_admin(itx: discord.Interaction) -> bool:
    try:
        return bool(itx.user and isinstance(itx.user, discord.Member) and itx.user.guild_permissions.administrator)
    except Exception:
        return False

@app_commands.check(lambda itx: _is_admin(itx))
@bot.tree.command(name="sync", description="Force sync slash příkazů (admin).")
async def sync_cmd(itx: discord.Interaction):
    gid = itx.guild.id if itx.guild else None
    if gid:
        # stejné chování jako při startu – zkopíruj globální příkazy do guildy a sync
        gobj = discord.Object(id=gid)
        bot.tree.copy_global_to(guild=gobj)
        out = await bot.tree.sync(guild=gobj)
        await itx.response.send_message(f"Synced {len(out)} cmds (guild: {gid})", ephemeral=True)
    else:
        out = await bot.tree.sync()
        await itx.response.send_message(f"Synced {len(out)} cmds (global)", ephemeral=True)

# ---- Globální check pro prefix příkazy ----
@bot.check
async def globally_block_commands(ctx: commands.Context):
    # Pokud to není rozpoznaný command (jen text), povol dál
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
    # token jen z bot_token.py (bez ENV) – zachováno podle tvého nasazení
    token = getattr(bot_token, "TOKEN", None)
    if not token or len(token) < 30:
        await send_console_log("[FATAL] Chybí validní bot token")
        print(ts(), "[FATAL] Chybí validní bot token")
        return
    await send_console_log("Token OK, startuji…")
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    try:
        print(ts(), "[DEBUG] Spouštění bota…")
        asyncio.run(main())
    except Exception as e:
        print(ts(), f"[ERROR] Chyba při spuštění bota: {e}")

