import discord
import asyncio
import os

async def check():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)
    # Load .env
    with open("/root/discord-bot/.env") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k] = v.strip('"').strip("'")
    
    token = os.environ.get("BOT_TOKEN")
    gid = 615171377783242769
    
    if not token:
        print("BOT_TOKEN not found!")
        return

    await client.login(token)
    guild = await client.fetch_guild(gid)
    
    print(f"--- Roles in Guild: {guild.name} ({guild.id}) ---")
    roles = await guild.fetch_roles()
    for role in sorted(roles, key=lambda r: r.position, reverse=True):
        print(f"Role: {role.name:25} | ID: {role.id}")
    print("-" * 40)
            
    await client.close()


if __name__ == "__main__":
    asyncio.run(check())
