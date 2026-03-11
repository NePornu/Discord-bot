
import asyncio
import os
import discord
import sys

# Add parent directory to path to find shared
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.python.config import config

async def main():
    intents = discord.Intents.all()
    # Use config.BOT_TOKEN if available, else check env
    token = config.BOT_TOKEN or os.getenv("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN not found.")
        return

    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user}")
        guild = bot.get_guild(config.GUILD_ID)
        if not guild:
            print(f"Guild {config.GUILD_ID} not found.")
            await bot.close()
            return

        print("\n--- CHANNELS ---")
        for channel in guild.text_channels:
            print(f"{channel.id}: {channel.name}")

        print("\n--- ROLES ---")
        for role in guild.roles:
            print(f"{role.id}: {role.name}")

        await bot.close()

    try:
        await bot.start(token)
    except Exception as e:
        print(f"Failed to start bot: {e}")

if __name__ == "__main__":
    asyncio.run(main())
