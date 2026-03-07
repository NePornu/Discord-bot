import discord
import os
import sys

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from config.dashboard_secrets import BOT_TOKEN
except ImportError:
    print("Error: BOT_TOKEN not found in config/dashboard_secrets.py")
    sys.exit(1)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    print("--- Guilds ---")
    for guild in client.guilds:
        print(f"Name: {guild.name}, ID: {guild.id}")
    await client.close()

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("No token.")
    else:
        client.run(BOT_TOKEN)
