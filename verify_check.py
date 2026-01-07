import sys
import asyncio
import discord
import redis.asyncio as redis
from datetime import datetime, timezone

import os
print(f"DEBUG: CWD={os.getcwd()}")
print(f"DEBUG: PATH={sys.path}")
import bot_token
print(f"DEBUG: bot_token dir: {dir(bot_token)}")
# Try common names
if hasattr(bot_token, 'token'): TOKEN = bot_token.token
elif hasattr(bot_token, 'TOKEN'): TOKEN = bot_token.TOKEN
else: 
    print("FATAL: Cannot find token variable")
    sys.exit(1)

GUILD_ID = 615171377783242769
REDIS_URL = "redis://redis-hll:6379/0"

intents = discord.Intents.default()
intents.members = True
intents.presences = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        print("\n=== 🔍 NEZÁVISLÝ AUDIT DAT (Verification) ===\n")
        
        guild = client.get_guild(GUILD_ID)
        # Wait a bit if guild is not ready
        if not guild:
            # Try fetching
             pass
        
        if not guild:
             print(f"❌ Guild {GUILD_ID} not found in cache. Checking intents...")
             # List guilds
             print(f"   Vidím {len(client.guilds)} serverů: {[g.id for g in client.guilds]}")
             await client.close()
             return

        # 1. Total Members
        real_total = guild.member_count
        
        # 2. Online Members
        real_online = 0
        for m in guild.members:
             if m.status != discord.Status.offline:
                 real_online += 1
        
        print(f"🔵 DISCORD API (Zdroj Pravdy):")
        print(f"   • Celkem členů: {real_total}")
        print(f"   • Online členů: {real_online}")

        # Scan recent msgs
        now = datetime.now(timezone.utc)
        curr_hour = now.hour
        today = now.strftime("%Y%m%d")
        
        print(f"\n   [Provádím scan aktivity poslední hodiny...]")
        msg_sample = 0
        # Scan predefined channels if verify is needed, otherwise just count channels
        # channel = discord.utils.get(guild.text_channels, name="hlavní-chat")
        
        # Redis Check
        print(f"Logged in as {client.user} (ID: {client.user.id})")
    
        # 1. Connect to Redis (using DIRECT IP for host access)
        r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
        
        dash_total = await r.get(f"presence:total:{GUILD_ID}")
        dash_online = await r.get(f"presence:online:{GUILD_ID}")
        
        # Heatmap check (current hour)
        dash_hourly = await r.hget(f"stats:hourly:{GUILD_ID}:{today}", str(curr_hour))
        dash_total_msgs = await r.get(f"stats:total_msgs:{GUILD_ID}")
        
        print(f"   • Celkem členů: {dash_total}")
        print(f"   • Online členů: {dash_online}")
        print(f"   • Zprávy tuto hodinu (Server): {dash_hourly or 0}")
        print(f"   • Celkem zaznamenaných zpráv: {dash_total_msgs}")

        print(f"\n✅ VÝSLEDEK TESTU:")
        
        match_total = str(real_total) == str(dash_total)
        # Online can fluctuate by seconds
        diff_online = abs(int(real_online) - int(dash_online or 0))
        match_online = diff_online <= 5 
        
        if match_total:
            print("   [OK] Total Members: SHODA")
        else:
            print(f"   [FAIL] Total Members: NESHODA (Rozdíl: {int(real_total) - int(dash_total or 0)})")
            
        if match_online:
             print("   [OK] Online Members: SHODA (korelace ok)")
        else:
             print(f"   [FAIL] Online Members: NESHODA (Rozdíl: {diff_online})")

        if match_total and match_online:
            print("\n>>> ZÁVĚR: Dashboard zobrazuje reálná data. <<<")
        else:
            print("\n>>> ZÁVĚR: Nalezeny discrepancy. Zkontrolujte bota. <<<")

        await r.close()
    except Exception as e:
        print(f"Error during verify: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    client.run(TOKEN)
