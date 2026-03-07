import discord
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

async def cleanup():
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    token = os.getenv("BOT_TOKEN")
    channel_id = 1425752839820677130 # The wrong channel 
    
    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}. Cleaning up channel {channel_id}...")
        channel = client.get_channel(channel_id)
        if not channel:
            print("Channel not found!")
            await client.close()
            return
            
        deleted = 0
        async for msg in channel.history(limit=50):
            if msg.author.id == client.user.id:
                # Check if it's a pattern alert (has embeds)
                if msg.embeds and any("Pattern Engine" in (e.footer.text or "") for e in msg.embeds):
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.5) # Avoid rate limits
        
        print(f"Deleted {deleted} incorrect alerts.")
        await client.close()

    await client.start(token)

if __name__ == "__main__":
    asyncio.run(cleanup())
