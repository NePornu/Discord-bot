#!/usr/bin/env python3
"""
Discord → Fluxer Sync Script
Syncs channels, roles, permissions, messages (with masquerade), and reactions.
Designed to be run repeatedly for incremental synchronization.

State is persisted in sync_state.json to track what has been synced.
"""

import discord
import json
import httpx
import asyncio
import os
import sys
import hashlib
from datetime import datetime, timezone

# ─── Configuration ───────────────────────────────────────────────────────────

TOKEN_FILE = "/root/discord-bot-secrets/bot_token.py"
if os.path.exists(TOKEN_FILE):
    import sys
    sys.path.append("/root/discord-bot-secrets")
    from bot_token import TOKEN as BOT_TOKEN
else:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

DISCORD_GUILD_ID = 615171377783242769
FLUXER_GUILD_ID = "1474016949225660417"
FLUXER_API = "http://fluxer-api-1:8080/v1"

with open("migration_token.txt", "r") as f:
    FLUXER_TOKEN = f.read().strip()

FLUXER_HEADERS = {
    "Authorization": FLUXER_TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

STATE_FILE = "sync_state.json"

# Channel type mapping: Discord → Fluxer
CHANNEL_TYPE_MAP = {
    discord.ChannelType.text: 0,
    discord.ChannelType.voice: 2,
    discord.ChannelType.category: 4,
    discord.ChannelType.news: 0,
    discord.ChannelType.stage_voice: 2,
}

if hasattr(discord.ChannelType, 'forum'):
    CHANNEL_TYPE_MAP[discord.ChannelType.forum] = 0

# ─── State Management ────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "channel_map": {},       # discord_channel_id -> fluxer_channel_id
        "category_map": {},      # discord_category_id -> fluxer_category_id
        "role_map": {},          # discord_role_id -> fluxer_role_id
        "webhook_map": {},       # fluxer_channel_id -> {webhook_id, token}
        "last_message_ids": {},  # discord_channel_id -> last_synced_message_id
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ─── Fluxer API Helpers ──────────────────────────────────────────────────────

# ─── Fluxer API Helpers ──────────────────────────────────────────────────────

# Global client for persistent connections
HTTP_CLIENT = httpx.AsyncClient(timeout=60.0, limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
SEMAPHORE = asyncio.Semaphore(50)  # High-speed parallelism

async def fluxer_request(method, path, json_data=None, max_retries=5):
    """Make a Fluxer API request with rate limit handling and semaphore pacing."""
    url = f"{FLUXER_API}{path}"
    async with SEMAPHORE:
        for attempt in range(max_retries):
            try:
                resp = await HTTP_CLIENT.request(method, url, headers=FLUXER_HEADERS, json=json_data)
                if resp.status_code == 429:
                    try:
                        retry_after = resp.json().get("retry_after", 10)
                    except Exception:
                        retry_after = 10
                    print(f"  ⏳ Rate limited, waiting {retry_after:.1f}s...")
                    await asyncio.sleep(retry_after + 1)
                    continue
                return resp
            except httpx.RequestError as e:
                print(f"  ❌ Request error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return None

async def get_fluxer_channels():
    resp = await fluxer_request("GET", f"/guilds/{FLUXER_GUILD_ID}/channels")
    return resp.json() if resp and resp.status_code == 200 else []

async def get_fluxer_roles():
    resp = await fluxer_request("GET", f"/guilds/{FLUXER_GUILD_ID}/roles")
    return resp.json() if resp and resp.status_code == 200 else []

# ─── Channel Sync ────────────────────────────────────────────────────────────

async def sync_channels(guild, state):
    print("\n═══ Syncing Channels ═══")
    existing = await get_fluxer_channels()
    
    # Categories
    categories = sorted(guild.categories, key=lambda c: c.position)
    for cat in categories:
        cat_id_str = str(cat.id)
        if cat_id_str in state["category_map"]: continue
        
        existing_cat = next((ch for ch in existing if ch["name"] == cat.name and ch["type"] == 4), None)
        if existing_cat:
            state["category_map"][cat_id_str] = existing_cat["id"]
        else:
            resp = await fluxer_request("POST", f"/guilds/{FLUXER_GUILD_ID}/channels", {"name": cat.name, "type": 4})
            if resp and resp.status_code == 200:
                state["category_map"][cat_id_str] = resp.json()["id"]
        await asyncio.sleep(0.1)

    # Channels
    for cat in categories:
        parent_id = state["category_map"].get(str(cat.id))
        for channel in sorted(cat.channels, key=lambda c: c.position):
            ch_id_str = str(channel.id)
            if ch_id_str in state["channel_map"]: continue
            
            fluxer_type = CHANNEL_TYPE_MAP.get(channel.type, 0)
            existing_ch = next((ch for ch in existing if ch["name"] == channel.name and ch["type"] == fluxer_type and ch.get("parent_id") == parent_id), None)
            
            if existing_ch:
                state["channel_map"][ch_id_str] = existing_ch["id"]
            else:
                payload = {"name": channel.name, "type": fluxer_type, "parent_id": parent_id, "topic": getattr(channel, 'topic', "") or ""}
                resp = await fluxer_request("POST", f"/guilds/{FLUXER_GUILD_ID}/channels", payload)
                if resp and resp.status_code == 200:
                    state["channel_map"][ch_id_str] = resp.json()["id"]
    save_state(state)

# ─── Role Sync ───────────────────────────────────────────────────────────────

async def sync_roles(guild, state):
    print("\n═══ Syncing Roles ═══")
    fluxer_roles = await get_fluxer_roles()
    fluxer_role_names = {r["name"]: r for r in fluxer_roles}

    for role in sorted(guild.roles, key=lambda r: r.position):
        role_id_str = str(role.id)
        if role_id_str in state["role_map"]: continue
        if role.name == "@everyone":
            state["role_map"][role_id_str] = FLUXER_GUILD_ID
            continue

        if role.name in fluxer_role_names:
            state["role_map"][role_id_str] = fluxer_role_names[role.name]["id"]
        else:
            payload = {"name": role.name, "permissions": str(role.permissions.value), "color": role.color.value, "hoist": role.hoist, "mentionable": role.mentionable}
            resp = await fluxer_request("POST", f"/guilds/{FLUXER_GUILD_ID}/roles", payload)
            if resp and resp.status_code == 200:
                state["role_map"][role_id_str] = resp.json()["id"]
    save_state(state)

# ─── Webhook Management ──────────────────────────────────────────────────────

async def get_or_create_webhook(fluxer_channel_id, state):
    if fluxer_channel_id in state["webhook_map"]:
        return state["webhook_map"][fluxer_channel_id]
    resp = await fluxer_request("POST", f"/channels/{fluxer_channel_id}/webhooks", {"name": "Discord Migration"})
    if resp and resp.status_code == 200:
        data = resp.json()
        state["webhook_map"][fluxer_channel_id] = {"id": data["id"], "token": data["token"]}
        save_state(state)
        return state["webhook_map"][fluxer_channel_id]
    return None

# ─── Message & Reaction Sync ─────────────────────────────────────────────────

async def process_message(msg, fluxer_ch_id, webhook_info, state, ch_id_str):
    """Processes a single message and its reactions with minimal latency."""
    if not (msg.content or msg.embeds or msg.attachments):
        state["last_message_ids"][ch_id_str] = str(msg.id)
        return

    payload = {
        "content": msg.content or "",
        "username": (msg.author.display_name or msg.author.name)[:80],
        "avatar_url": str(msg.author.display_avatar.url) if getattr(msg.author, 'display_avatar', None) else None,
        "embeds": [e.to_dict() for e in msg.embeds[:10]] if msg.embeds else None
    }

    resp = await fluxer_request("POST", f"/webhooks/{webhook_info['id']}/{webhook_info['token']}?wait=true", payload)
    if resp and resp.status_code == 200:
        fluxer_msg_id = resp.json().get("id")
        if msg.reactions and fluxer_msg_id:
            # Parallelize reactions for the same message
            await asyncio.gather(*(sync_reaction(r, fluxer_ch_id, fluxer_msg_id) for r in msg.reactions))
        state["last_message_ids"][ch_id_str] = str(msg.id)

async def sync_reaction(reaction, fluxer_ch_id, fluxer_msg_id):
    emoji_str = reaction.emoji if isinstance(reaction.emoji, str) else getattr(reaction.emoji, 'name', None)
    if not emoji_str: return
    import urllib.parse
    await fluxer_request("PUT", f"/channels/{fluxer_ch_id}/messages/{fluxer_msg_id}/reactions/{urllib.parse.quote(emoji_str)}/@me")

async def sync_messages(guild, state):
    print("\n═══ Syncing Messages (Optimized) ═══")
    for channel in sorted(guild.text_channels, key=lambda c: c.position):
        ch_id_str = str(channel.id)
        fluxer_ch_id = state["channel_map"].get(ch_id_str)
        if not fluxer_ch_id: continue

        webhook_info = await get_or_create_webhook(fluxer_ch_id, state)
        if not webhook_info: continue

        last_sync_id = state["last_message_ids"].get(ch_id_str)
        after = discord.Object(id=int(last_sync_id)) if last_sync_id else None
        
        print(f"  📨 Syncing #{channel.name}...")
        msg_count = 0
        tasks = []
        
        # STREAMING: Process messages as they arrive without keeping them in memory
        async for msg in channel.history(limit=None, after=after, oldest_first=True):
            tasks.append(process_message(msg, fluxer_ch_id, webhook_info, state, ch_id_str))
            msg_count += 1
            
            # Batch concurrent processing
            if len(tasks) >= 50:
                await asyncio.gather(*tasks)
                tasks = []
                if msg_count % 100 == 0:
                    save_state(state)
                    print(f"    ... {msg_count} messages")
        
        if tasks: await asyncio.gather(*tasks)
        save_state(state)
        print(f"    ✅ #{channel.name} complete ({msg_count} msgs)")

# ─── Main ────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.reactions = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"🚀 Logged in as {client.user}")
    guild = client.get_guild(DISCORD_GUILD_ID)
    if not guild: return await client.close()

    state = load_state()
    await sync_channels(guild, state)
    await sync_roles(guild, state)
    await sync_messages(guild, state)
    
    await HTTP_CLIENT.aclose()
    print("\n═══ Sync Complete! ═══")
    await client.close()

if __name__ == "__main__":
    client.run(BOT_TOKEN)
