  GNU nano 3.2                                                                                           bot.py                                                                                                     

import discord
from discord.ext import commands
import os
import bot_token
import config
import asyncio
import time
import platform
import sys
from datetime import datetime

def ts():
    """Vrací časovou značku ve formátu [YYYY-MM-DD HH:MM:SS]"""
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=config.BOT_PREFIX, intents=intents)
pending_console_msgs = []

async def send_console_log(msg: str):
    """
    Pošle log zprávu do Discord kanálu určeného pro konzoli (log kanál).
    Pokud kanál není dostupný, zpráva se uloží a odešle později při on_ready.
    """
    fullmsg = f"{ts()} {msg}"
    try:
        if not bot.is_ready():
            pending_console_msgs.append(fullmsg)
            print(f"[PENDING] {fullmsg}")
            return
        channel = bot.get_channel(config.CONSOLE_CHANNEL_ID)
        if channel:
            # Pokud je zpráva moc dlouhá, rozděl na části kvůli limitu Discordu (2000 znaků)
            chunks = [fullmsg[i:i+1900] for i in range(0, len(fullmsg), 1900)]
            for chunk in chunks:
                await channel.send(f"```{chunk}```")
        else:
            print(f"[ERROR] Nelze najít console channel s ID {config.CONSOLE_CHANNEL_ID}")
    except Exception as e:
        print(f"[ERROR] send_console_log failed: {e}")

async def log_start_info():
    await send_console_log("=== SPUŠTĚNÍ BOTA LOG ===") 
    await send_console_log(f"Platforma: {platform.platform()} | Python: {sys.version.replace(chr(10), ' ')}")
    await send_console_log(f"discord.py verze: {discord.__version__}")
    await send_console_log(f"PID: {os.getpid()} | Working dir: {os.getcwd()}")
                                                                                                 [ Read 157 lines ]
^G Get Help      ^O Write Out     ^W Where Is      ^K Cut Text      ^J Justify       ^C Cur Pos       M-U Undo         M-A Mark Text    M-] To Bracket   M-Q Previous     ^B Back          ^◀ Prev Word
^X Exit          ^R Read File     ^\ Replace       ^U Uncut Text    ^T To Spell      ^_ Go To Line    M-E Redo         M-6 Copy Text    ^Q Where Was     M-W Next         ^F Forward       ^▶ Next Word
