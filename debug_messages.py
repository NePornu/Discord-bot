import discord
import os

TOKEN = None
try:
    with open('/app/.env', 'r') as f:
        for line in f:
            if line.startswith('BOT_TOKEN='):
                TOKEN = line.split('=')[1].strip().strip('"')
except Exception as e:
    print(f"Error reading .env: {e}")

GUILD_ID = 615171377783242769

class DebugClient(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        guild = self.get_guild(GUILD_ID)
        if not guild:
            print("Guild not found")
            await self.close()
            return
            
        print("Available channels:")
        for c in guild.text_channels:
            print(f"- {c.name}")
            
        target_channel = guild.text_channels[0] # just pick the first one to test reading
        print(f"\nReading from {target_channel.name}...")
        count = 0
        async for msg in target_channel.history(limit=20):
            if not msg.author.bot:
                print(f"{msg.author.name}: {msg.content}")
                count += 1
            if count >= 5:
                break
                    
        await self.close()

intents = discord.Intents.default()
intents.message_content = True
client = DebugClient(intents=intents)
client.run(TOKEN)
