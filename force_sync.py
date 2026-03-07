import asyncio
import os
import discord
from discord.ext import commands

async def main():
    token = os.getenv("BOT_TOKEN")
    bot = commands.Bot(command_prefix="*", intents=discord.Intents.default())
    
    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user}")
        print("Syncing global commands...")
        cmds = await bot.tree.sync()
        print(f"Synced {len(cmds)} global commands.")
        await bot.close()
        
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
