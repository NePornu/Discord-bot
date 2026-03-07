import discord
import json
import asyncio
import os

TOKEN = os.getenv("BOT_TOKEN")
GUILD_ID = 615171377783242769
VERIFICATION_CHANNEL_ID = 1459269521440506110
VERIFIED_ROLE_ID = 1179506149951811734
STATE_FILE = '/app/data/verification_state.json' # Path inside container

intents = discord.Intents.all()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (discord.py {discord.__version__})")
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

    print(f"Found {len(state)} users in state.")

    # Clear old bot messages in the channel to start fresh
    print("Clearing channel of recent bot messages...")
    try:
        def is_me(m):
            return m.author == client.user
        deleted = await channel.purge(limit=100, check=is_me)
        print(f"Deleted {len(deleted)} messages.")
    except Exception as e:
        print(f"Purge failed: {e}")

    role = guild.get_role(VERIFIED_ROLE_ID)
    if not role:
        print(f"CRITICAL: Role {VERIFIED_ROLE_ID} not found!")

    for uid_str, st in state.items():
        if st.get("status") == "VERIFIED":
            continue
            
        uid = int(uid_str)
        member = guild.get_member(uid)
        if not member:
            print(f"Member {uid} not on server, skipping.")
            continue
            
        print(f"Processing {member.name} ({uid})...")
        
        # 1. Assign role
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Verification Reset")
                print(f"  Role added.")
            except Exception as e:
                print(f"  Failed to add role: {e}")

        # 2. Resend DM with OTP
        otp = st.get("otp")
        if not otp:
            import string
            import random
            otp = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            state[uid_str]["otp"] = otp

        dm_msg = (
            f"**🔒 Ověření účtu**\n\n"
            f"Ahoj **{member.name}**! Vítej na serveru.\n"
            f"Pro dokončení ověření prosím pošli sem do chatu tento kód:\n\n"
            f"> **`{otp}`**\n\n"
        )
        try:
            await member.send(dm_msg)
            print(f"  DM sent.")
        except Exception as e:
            print(f"  DM failed: {e}")

        # 3. Post new message in waiting room
        created_at_fmt = f"<t:{int(member.created_at.timestamp())}:f> (<t:{int(member.created_at.timestamp())}:R>)"
        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
        bio_text = getattr(member, 'bio', "Bio není dostupné") or "Bio není dostupné"
        
        desc = (
            f"**Nový uživatel se připojil na server!**\n\n"
            f"**Uživatel:** {member.mention} ({member.name})\n"
            f"**ID:** {member.id}\n"
            f"**Účet vytvořen:** {created_at_fmt}\n"
            f"**Avatar:** [Odkaz]({avatar_url})\n"
            f"**Bio:** {bio_text}\n\n"
            f"Automaticky mu byla přidělena ověřovací role.\n\n"
            f"⏳ **Status:** Čeká na zadání kódu..."
        )
        
        # View with correct custom_ids for the new code
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Schválit (Approve)", style=discord.ButtonStyle.success, emoji="✅", custom_id="verif_approve", disabled=True))
        view.add_item(discord.ui.Button(label="Upozornit", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="verif_warn"))
        view.add_item(discord.ui.Button(label="Vyhodit (Kick)", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="verif_kick"))
        
        try:
            m = await channel.send(desc, view=view)
            state[uid_str]["verification_message_id"] = m.id
            state[uid_str]["status"] = "PENDING"
            print(f"  Channel post created.")
        except Exception as e:
            print(f"  Channel post failed: {e}")

    # Save updated state
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)
        
    print("\nInitialization complete.")
    await client.close()

if __name__ == "__main__":
    client.run(TOKEN)
