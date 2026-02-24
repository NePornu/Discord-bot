import json
import requests
import time
import os

API_URL = "http://fluxer-api-1:8080/v1"
BOT_TOKEN = "MTIyNzI2OTU5OTk1MTU4OTUwOA.GsCoHP.OEpQd6iF6thu7cbvnBl3c5-48rIREWgoLEY6MY"

HEADERS = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

TYPE_MAP = {
    "category": 4,
    "text": 0,
    "voice": 2,
}

def create_guild(name):
    payload = {"name": name}
    url = f"{API_URL}/guilds"
    print(f"Creating guild '{name}'...")
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            guild_id = data["id"]
            print(f"✅ Created Guild: {name} (ID: {guild_id})")
            return guild_id
        else:
            print(f"❌ Failed to create guild: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating guild: {e}")
        return None

def create_channel(guild_id, name, type_str, parent_id=None):
    fluxer_type = TYPE_MAP.get(type_str, 0)
    payload = {
        "name": name,
        "type": fluxer_type,
        "topic": f"Training channel for {name}",
        "parent_id": parent_id
    }
    url = f"{API_URL}/guilds/{guild_id}/channels"
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            channel_id = data["id"]
            return channel_id
        else:
            print(f"❌ Failed to create channel: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating channel: {e}")
        return None

def create_invite(channel_id):
    url = f"{API_URL}/channels/{channel_id}/invites"
    payload = {"max_age": 0, "max_uses": 0, "temporary": False}
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code == 200:
        return resp.json()["code"]
    return None

def main():
    guild_id = create_guild("Moderator Training Ground (Bot Instance)")
    if not guild_id:
        return

    structure = [
        {
            "name": "🚩 Training Hall",
            "type": "category",
            "channels": [
                {"name": "rules-and-info", "type": "text"},
                {"name": "nsfw-practice", "type": "text"},
                {"name": "spam-practice", "type": "text"},
                {"name": "raiding-simulation", "type": "text"},
                {"name": "chat-moderation", "type": "text"},
            ]
        }
    ]

    first_text_chan_id = None

    for cat in structure:
        cat_id = create_channel(guild_id, cat["name"], cat["type"])
        if cat_id:
            for chan in cat["channels"]:
                chan_id = create_channel(guild_id, chan["name"], chan["type"], parent_id=cat_id)
                if not first_text_chan_id and chan["type"] == "text":
                    first_text_chan_id = chan_id
                time.sleep(0.5)

    print(f"\n✅ Training Ground setup complete! Target Guild ID: {guild_id}")
    
    with open("training_ground_config.json", "w") as f:
        json.dump({"guild_id": str(guild_id)}, f)

    if first_text_chan_id:
        code = create_invite(first_text_chan_id)
        print(f"\n🎉 INVITE LINK FOR USERS: https://chat.nepornu.cz/invite/{code}")

if __name__ == "__main__":
    main()
