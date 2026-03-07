"""
Re-send verification messages in the CORRECT format matching on_member_join.
Deletes old ugly messages and sends new ones.
"""
import discord
from discord import ui
import json
import os
from datetime import datetime

TOKEN = os.getenv("BOT_TOKEN")
STATE_FILE = '/app/data/verification_state.json'

GUILD_ID = 615171377783242769
VERIFICATION_CHANNEL_ID = 1459269521440506110

with open(STATE_FILE, 'r') as f:
    state = json.load(f)

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

    # Find all non-verified users still on server
    pending_users = {uid: st for uid, st in state.items() 
                     if st.get("status") in ("PENDING", "WAITING_FOR_APPROVAL")
                     and guild.get_member(int(uid))}
    
    print(f"Found {len(pending_users)} active pending users.")

    # Delete old verification messages first
    for uid, st in pending_users.items():
        old_msg_id = st.get("verification_message_id")
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(int(old_msg_id))
                await old_msg.delete()
                print(f"  Deleted old message {old_msg_id}")
            except:
                pass

    # Send new messages in the CORRECT format
    for uid, st in pending_users.items():
        member_id = int(uid)
        member = guild.get_member(member_id)
        if not member:
            continue

        status = st.get("status", "PENDING")
        waiting = status == "WAITING_FOR_APPROVAL"
        
        created_at_fmt = f"<t:{int(member.created_at.timestamp())}:f> (<t:{int(member.created_at.timestamp())}:R>)"
        avatar_url = member.display_avatar.url
        bio_text = getattr(member, 'bio', "Bio není dostupné") or "Bio není dostupné"

        if waiting:
            status_text = "⏳ **Status:** WAITING_FOR_APPROVAL"
        else:
            status_text = "⏳ **Status:** Čeká na propojení přes portál..."
        
        desc = (
            f"**Nový uživatel se připojil na server!**\n\n"
            f"**Uživatel:** {member.mention} ({member.name})\n"
            f"**ID:** {member.id}\n"
            f"**Účet vytvořen:** {created_at_fmt}\n"
            f"**Avatar:** [Odkaz]({avatar_url})\n"
            f"**Bio:** {bio_text}\n\n"
            f"{status_text}"
        )

        # Create view with DYNAMIC custom_ids
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            label="Schválit (Approve)", style=discord.ButtonStyle.success,
            emoji="✅", custom_id=f"verif_approve:{member_id}",
            disabled=not waiting,
        ))
        view.add_item(discord.ui.Button(
            label="Upozornit", style=discord.ButtonStyle.secondary,
            emoji="⚠️", custom_id=f"verif_warn:{member_id}",
        ))
        view.add_item(discord.ui.Button(
            label="Vyhodit (Kick)", style=discord.ButtonStyle.danger,
            emoji="🚪", custom_id=f"verif_kick:{member_id}",
        ))

        msg = await channel.send(desc, view=view)
        state[uid]["verification_message_id"] = msg.id
        print(f"  ✅ {member.name} ({uid}), msg_id={msg.id}, status={status}")

    # Save
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

    print("Done. Exiting.")
    await client.close()

client.run(TOKEN)
