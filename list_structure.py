import discord
import os
import sys
import json

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from config.dashboard_secrets import BOT_TOKEN
except ImportError:
    print("Error: BOT_TOKEN not found in config/dashboard_secrets.py")
    sys.exit(1)

GUILD_ID = 615171377783242769

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print(f"Could not find guild with ID {GUILD_ID}")
        await client.close()
        return

    structure = []
    
    # Categories
    categories = sorted(guild.categories, key=lambda c: c.position)
    
    for category in categories:
        cat_data = {
            "id": category.id,
            "name": category.name,
            "position": category.position,
            "type": "category",
            "channels": []
        }
        
        # Channels in category
        for channel in category.channels:
            chan_data = {
                "id": channel.id,
                "name": channel.name,
                "type": str(channel.type),
                "position": channel.position
            }
            cat_data["channels"].append(chan_data)
            
        structure.append(cat_data)
        
    # Channels without category
    orphan_channels = [c for c in guild.channels if not c.category]
    if orphan_channels:
        cat_data = {
            "id": None,
            "name": "Uncategorized",
            "position": -1,
            "type": "category",
            "channels": []
        }
        for channel in orphan_channels:
             chan_data = {
                "id": channel.id,
                "name": channel.name,
                "type": str(channel.type),
                "position": channel.position
            }
             cat_data["channels"].append(chan_data)
        structure.append(cat_data)

    print(json.dumps(structure, indent=2))
    await client.close()

if __name__ == "__main__":
    client.run(BOT_TOKEN)
