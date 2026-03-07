import discord
import json
import asyncio
import os

TOKEN = os.getenv("BOT_TOKEN")
GUILD_ID = 615171377783242769
VERIFICATION_CHANNEL_ID = 1459269521440506110
VERIFIED_ROLE_ID = 1179506149951811734
STATE_FILE = '/root/discord-bot/data/verification_state.json'

intents = discord.Intents.all()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("Guild not found!")
        await client.close()
        return
        
    channel = guild.get_channel(VERIFICATION_CHANNEL_ID)
    if not channel:
        print("Channel not found!")
        await client.close()
        return
    
    # Load state
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    else:
        state = {}
    
    # Clear channel
    print("Clearing channel...")
    try:
        deleted = await channel.purge(limit=100, check=lambda m: m.author == client.user)
        print(f"Deleted {len(deleted)} messages.")
    except Exception as e:
        print(f"Purge failed: {e}")
    
    role = guild.get_role(VERIFIED_ROLE_ID)
    if not role:
        print(f"Role {VERIFIED_ROLE_ID} not found!")
    
    for uid, st in state.items():
        if st.get("status") == "VERIFIED": continue
        
        member = guild.get_member(int(uid))
        if not member: continue
        
        print(f"Processing {member.name} ({uid})...")
        
        # Add role
        if role and role not in member.roles:
            try:
                await member.add_roles(role)
                print(f"  Added role to {member.name}")
            except Exception as e:
                print(f"  Failed to add role: {e}")
            
        # Send DM
        otp = st.get("otp", "RESTART")
        msg = (
            f"**🔒 Ověření účtu**\n\n"
            f"Ahoj **{member.name}**! Vítej na serveru.\n"
            f"Pro dokončení ověření prosím pošli sem do chatu tento kód:\n\n"
            f"> **`{otp}`**\n\n"
        )
        try:
            await member.send(msg)
            print(f"  Sent DM to {member.name}")
        except Exception as e:
            print(f"  Failed to send DM to {member.name}: {e}")
            
        # Post in channel
        created_at_fmt = f"<t:{int(member.created_at.timestamp())}:f> (<t:{int(member.created_at.timestamp())}:R>)"
        avatar_url = member.display_avatar.url
        bio_text = getattr(member, 'bio', "Bio není dostupné") or "Bio není dostupné"
        
        desc = (
            f"**Nový uživatel se připojil na server!**\n\n"
            f"**Uživatel:** {member.mention} ({member.name})\n"
            f"**ID:** {member.id}\n"
            f"**Účet vytvořen:** {created_at_fmt}\n"
            f"**Avatar:** {avatar_url}\n"
            f"**Bio:** {bio_text}\n\n"
            f"Automaticky mu byla přidělena ověřovací role.\n\n"
            f"⏳ **Status:** Čeká na zadání kódu..."
        )
        
        # View matching new code's custom_ids
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Schválit (Approve)", style=discord.ButtonStyle.success, emoji="✅", custom_id="verif_approve", disabled=True))
        view.add_item(discord.ui.Button(label="Upozornit", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="verif_warn"))
        view.add_item(discord.ui.Button(label="Vyhodit (Kick)", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="verif_kick"))
        
        try:
            m = await channel.send(desc, view=view)
            state[uid]["verification_message_id"] = m.id
            state[uid]["status"] = "PENDING"
        except Exception as e:
            print(f"  Failed to post message: {e}")
        
    # Save state
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)
        
    print("All done!")
    await client.close()

client.run(TOKEN)
