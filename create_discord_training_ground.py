import discord
import asyncio
import json

TOKEN = "MTIyNzI2OTU5OTk1MTU4OTUwOA.GsCoHP.OEpQd6iF6thu7cbvnBl3c5-48rIREWgoLEY6MY"

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user} - creating Discord Training Ground...")
    
    # Check if we already created it
    for guild in client.guilds:
        if guild.name == "Moderator Training Ground":
            print(f"Server already exists: {guild.name} (ID: {guild.id})")
            
            # Recreate invite
            channel = guild.text_channels[0]
            invite = await channel.create_invite(max_age=0, max_uses=0)
            print(f"INVITE LINK: {invite.url}")
            
            with open("training_ground_config.json", "w") as f:
                json.dump({"guild_id": guild.id}, f)
            await client.close()
            return

    try:
        # Create the guild
        guild = await client.create_guild(name="Moderator Training Ground")
        print(f"✅ Created Discord Guild: {guild.name} (ID: {guild.id})")
        
        # Build structure
        cat = await guild.create_category("🚩 Training Hall")
        await guild.create_text_channel("rules-and-info", category=cat)
        await guild.create_text_channel("nsfw-practice", category=cat)
        await guild.create_text_channel("spam-practice", category=cat)
        await guild.create_text_channel("raiding-simulation", category=cat)
        general = await guild.create_text_channel("chat-moderation", category=cat)
        
        # Save config
        with open("training_ground_config.json", "w") as f:
            json.dump({"guild_id": guild.id}, f)
            
        print("✅ Config saved.")
        
        # Create Invite
        invite = await general.create_invite(max_age=0, max_uses=0)
        print(f"🎉 DISCORD INVITE LINK: {invite.url}")
        
    except Exception as e:
        print(f"❌ Error creating guild: {e}")
        
    await client.close()

client.run(TOKEN)
