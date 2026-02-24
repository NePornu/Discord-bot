import discord
import os
import asyncio

# Manual .env loading
env_path = "/root/discord-bot/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val.strip('"').strip("'")

token = os.getenv("BOT_TOKEN")

intents = discord.Intents.all()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user} ({client.user.id})")
    print(f"Guilds ({len(client.guilds)}):")
    for guild in client.guilds:
        print(f" - {guild.name} ({guild.id})")
    
    permissions = discord.Permissions.all()
    # Manual invite link generation for Revolt/Fluxer-like systems if possible,
    # but let's just show the ID.
    print(f"\nBot ID: {client.user.id}")
    print(f"Invite URL: https://discord.com/oauth2/authorize?client_id={client.user.id}&permissions=8&scope=bot%20applications.commands")
    
    await client.close()

if token:
    client.run(token)
else:
    print("BOT_TOKEN not found")
