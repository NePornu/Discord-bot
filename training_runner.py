import httpx
import asyncio
import json
import time
import sys
import re
import datetime

API_URL = "http://fluxer-api-1:8080/v1"

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

with open("migration_token.txt", "r") as f:
    AUTH_TOKEN = f.read().strip()

try:
    with open("training_ground_config.json", "r") as f:
        config = json.load(f)
        GUILD_ID = config["guild_id"]
except FileNotFoundError:
    log("Run create_training_ground.py first.")
    exit(1)

HEADERS = {
    "Authorization": AUTH_TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

WEBHOOKS = {}
ACTIVE_TRAINING_CHANNELS = set() 

# Very long timeout due to high Cassandra/API load
TIMEOUT = httpx.Timeout(60.0)

async def api_request(method, endpoint, json_data=None):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        url = f"{API_URL}{endpoint}"
        kwargs = {"headers": HEADERS}
        if json_data is not None:
             kwargs["json"] = json_data
        
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in [200, 201, 204]:
                try:
                    return resp.json() if resp.status_code != 204 else True
                except:
                    return True
            else:
                log(f"API Error {method} {endpoint}: {resp.status_code}")
                return None
        except Exception as e:
            log(f"Request Exception {method} {endpoint}: {repr(e)}")
            return None

async def send_message(channel_id, content, author_name="System", avatar_url=None):
    webhook_id = WEBHOOKS.get(channel_id)
    webhook_token = None
    
    if not webhook_id:
        w_resp = await api_request("POST", f"/channels/{channel_id}/webhooks", {"name": "Training Webhook"})
        if w_resp:
            webhook_id = w_resp["id"]
            webhook_token = w_resp["token"]
            WEBHOOKS[channel_id] = (webhook_id, webhook_token)
    else:
        webhook_id, webhook_token = WEBHOOKS[channel_id]

    payload = {
        "content": content,
        "username": author_name
    }
    if avatar_url:
        payload["avatar_url"] = avatar_url

    if webhook_id and webhook_token:
        log(f"Sending message to {channel_id} via webhook...")
        await api_request("POST", f"/webhooks/{webhook_id}/{webhook_token}?wait=true", payload)

async def create_channel(name, ch_type, parent_id=None, overwrites=None):
    payload = {"name": name, "type": ch_type}
    if parent_id: payload["parent_id"] = parent_id
    if overwrites: payload["permission_overwrites"] = overwrites
    ch = await api_request("POST", f"/guilds/{GUILD_ID}/channels", payload)
    if ch and ch.get("id"):
        ACTIVE_TRAINING_CHANNELS.add(ch["id"])
    return ch

async def delete_channel(channel_id):
    if channel_id in ACTIVE_TRAINING_CHANNELS:
        ACTIVE_TRAINING_CHANNELS.remove(channel_id)
    await api_request("DELETE", f"/channels/{channel_id}")

# --- Scenarios ---

async def run_scenario_spam(channel_id):
    log(f"Spawning SPAM in {channel_id}")
    spam_messages = [
        "FREE NITRO: http://scam.link/nitro",
        "Join my server!!! discord.gg/spam",
        "Hey look at this cool game: http://malware.com",
    ]
    for _ in range(3):
        for msg in spam_messages:
            await send_message(channel_id, msg, "Spambot", "https://cdn.discordapp.com/embed/avatars/1.png")
            await asyncio.sleep(1)
    await send_message(channel_id, "🚨 **System:** Úkol pro moderátora: Očistěte tento spam.", "System")

async def run_scenario_nsfw(channel_id):
    log(f"Spawning NSFW in {channel_id}")
    scenarios = [
        {"username": "HornyTeen69", "avatar": "https://i.pravatar.cc/150?u=1", "content": "Koukněte na tyhle fotky! 🔥 http://leak-content.io/gallery/123"},
        {"username": "OnlyFansPromo", "avatar": "https://i.pravatar.cc/150?u=2", "content": "Sleva 50% na můj obsah jen dnes přes tento link: [SIMULOVANÝ LINK]"},
        {"username": "AnonymousUser", "avatar": "https://i.pravatar.cc/150?u=3", "content": "Posílám spicy věci..."}
    ]
    for s in scenarios:
        await send_message(channel_id, s["content"], s["username"], s["avatar"])
        await asyncio.sleep(2)
    await send_message(channel_id, "🚨 **System:** Úkol pro moderátora: Promazat obsah.", "System")

async def run_scenario_boundary(channel_id):
    log(f"Spawning BOUNDARY in {channel_id}")
    content = "**[SOUKROMÁ ZPRÁVA - SIMULACE]**\nAhoj moderátore, cítím se hrozně sám. Mohl bys mi věnovat pár hodin každý večer? Ozvi se prosím."
    await send_message(channel_id, content, "ZmatenyUzivatel", "https://i.pravatar.cc/150?u=50")
    await asyncio.sleep(2)
    await send_message(channel_id, "💡 *Úkol: Reagovat podle manuálu (nastavení hranic).*")

async def run_scenario_crisis(channel_id):
    log(f"Spawning CRISIS in {channel_id}")
    content = "Už to nezvládám, všechno je zbytečné. Mám v šuplíku prášky a dneska s tím skončím. Sbohem všem."
    await send_message(channel_id, content, "Zoufalec", "https://i.pravatar.cc/150?u=99")
    await asyncio.sleep(2)
    await send_message(channel_id, "‼️ **POZOR:** Krizová situace. Okamžitě nasadit krizový protokol.", "System")


def extract_user_id(mention):
    match = re.search(r'<@!?(\d+)>', mention)
    return match.group(1) if match else None

async def handle_start(parts, root_channel_id, author_id, author_mention):
    trainee_id = None
    coach_id = None
    trainee_mention = None

    if len(parts) == 1:
        trainee_id = str(author_id)
        trainee_mention = str(author_mention)
    elif len(parts) >= 3:
        trainee_mention = parts[1]
        trainee_id = extract_user_id(trainee_mention)
        coach_id = extract_user_id(parts[2])
    else:
        await send_message(root_channel_id, "⚠️ Použití: `!t_start` nebo `!t_start @Cvičenec @Trenér`")
        return

    if not trainee_id:
        log(f"Invalid trainee ID extracted from {trainee_mention}")
        return

    log(f"Creating training space for trainee={trainee_id}")
    await send_message(root_channel_id, f"⌛ Vytvářím tréninkové prostředí pro {trainee_mention}...")

    overwrites = [
        {"id": str(GUILD_ID), "type": 0, "deny": "3072"},
        {"id": str(trainee_id), "type": 1, "allow": "3072"}
    ]
    if coach_id:
        overwrites.append({"id": str(coach_id), "type": 1, "allow": "3072"})
    
    cat = await create_channel(f"🎓 Trénink: {trainee_id}", 4, overwrites=overwrites)
    if not cat: return
    cat_id = cat["id"]

    ch1 = await create_channel("zadani-a-teorie", 0, parent_id=cat_id)
    ch2 = await create_channel("nsfw-simulace", 0, parent_id=cat_id)
    ch3 = await create_channel("spam-simulace", 0, parent_id=cat_id)
    ch4 = await create_channel("krizove-situace", 0, parent_id=cat_id)

    if ch1:
        msg_text = f"Vítejte!\n\nPříkazy:\n- `!t_scenario nsfw`\n- `!t_scenario spam`\n- `!t_scenario boundary`\n- `!t_scenario crisis`\n\nUkončení: `!t_finish <shrnutí>`."
        await send_message(ch1["id"], msg_text)

    await send_message(root_channel_id, f"✅ Tréninkový prostor vytvořen.")


async def handle_finish(msg, author_id):
    channel_id = msg["channel_id"]
    log(f"Handling !t_finish in {channel_id}")
    ch_info = await api_request("GET", f"/channels/{channel_id}")
    if not ch_info or not ch_info.get("parent_id"):
        await send_message(channel_id, "⚠️ Použijte jen uvnitř tréninkové sekce.")
        return
    
    cat_id = ch_info["parent_id"]
    trigger_text = "!t_finish"
    content = msg.get("content", "")
    summary = content[content.find(trigger_text)+len(trigger_text):].strip() or "Dokončeno."

    cat_info = await api_request("GET", f"/channels/{cat_id}")
    trainee_id = cat_info["name"].split(": ")[1] if cat_info and ": " in cat_info["name"] else None

    if trainee_id:
        dm_ch = await api_request("POST", "/users/@me/channels", {"recipient_id": trainee_id})
        if dm_ch:
            await api_request("POST", f"/channels/{dm_ch['id']}/messages", {"content": f"**Hodnocení tréninku:**\n{summary}"})

    guild_channels = await api_request("GET", f"/guilds/{GUILD_ID}/channels")
    if guild_channels:
        for c in guild_channels:
            if c.get("parent_id") == cat_id:
                await delete_channel(c["id"])
        await delete_channel(cat_id)

async def poll_commands():
    log("🚀 Starting Optimized REST API Poller (v3 - High Load Resilience)...")
    
    channels_resp = await api_request("GET", f"/guilds/{GUILD_ID}/channels")
    if not channels_resp:
        log("Failed to load initial channels. Exiting poller.")
        return
    
    cmd_ch_id = None
    for c in channels_resp:
        if c["name"] == "chat-moderation":
            cmd_ch_id = c["id"]
        if c.get("parent_id"):
            p_ch = next((x for x in channels_resp if x["id"] == c["parent_id"]), None)
            if p_ch and "Trénink:" in p_ch["name"]:
                ACTIVE_TRAINING_CHANNELS.add(c["id"])

    log(f"Initial polling targets: {len(ACTIVE_TRAINING_CHANNELS)} (practice) + {cmd_ch_id} (cmd)")

    last_ids = {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while True:
            try:
                targets = list(ACTIVE_TRAINING_CHANNELS)
                if cmd_ch_id: targets.insert(0, cmd_ch_id)
                
                log(f"Polling {len(targets)} channels...")
                for tid in targets:
                    url = f"{API_URL}/channels/{tid}/messages?limit=5"
                    resp = await client.get(url, headers=HEADERS)
                    if resp.status_code == 200:
                        msgs = resp.json()
                        if not msgs: continue
                        if tid not in last_ids:
                            last_ids[tid] = msgs[0]["id"]
                            continue
                        
                        for m in reversed(msgs):
                            if int(m["id"]) > int(last_ids[tid]):
                                last_ids[tid] = m["id"]
                                content = m.get("content", "").strip()
                                author_name = m.get("author", {}).get("username")
                                
                                log(f"[{tid}] {author_name}: {content}")
                                
                                if author_name in ["System", "Spambot", "Zoufalec", "ZmatenyUzivatel"]:
                                    continue
                                
                                parts = content.split()
                                if not parts: continue
                                cmd = parts[0].lower()
                                
                                if cmd == "!t_start":
                                    aid = m["author"]["id"]
                                    asyncio.create_task(handle_start(parts, tid, aid, f"<@{aid}>"))
                                elif cmd == "!t_scenario":
                                    if len(parts)>1:
                                        sc = parts[1].lower()
                                        if sc=="spam": asyncio.create_task(run_scenario_spam(tid))
                                        elif sc=="nsfw": asyncio.create_task(run_scenario_nsfw(tid))
                                        elif sc=="boundary": asyncio.create_task(run_scenario_boundary(tid))
                                        elif sc=="crisis": asyncio.create_task(run_scenario_crisis(tid))
                                elif cmd == "!t_finish":
                                    asyncio.create_task(handle_finish(m, m["author"]["id"]))
                    else:
                        log(f"Failed to poll {tid}: {resp.status_code}")
                
                # Sleep longer to reduce load on Cassandra
                await asyncio.sleep(5)
            except Exception as e:
                log(f"Poll Loop Error: {repr(e)}")
                await asyncio.sleep(10)

async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        await poll_commands()

if __name__ == "__main__":
    asyncio.run(main())
