import json
import requests
import time
import os

# Fluxer Configuration
API_URL = "http://fluxer-api-1:8080/v1"

# Read Token
try:
    with open("migration_token.txt", "r") as f:
        AUTH_TOKEN = f.read().strip()
except FileNotFoundError:
    print("❌ migration_token.txt not found. Please run create_session.py first.")
    exit(1)

HEADERS = {
    "Authorization": AUTH_TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

# Mapping Discord Types to Fluxer Types (re-using from migrate_structure.py)
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
    print(f"Creating channel '{name}' (Type: {type_str})...")
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            channel_id = data["id"]
            print(f"✅ Created Channel: {name} (ID: {channel_id})")
            return channel_id
        else:
            print(f"❌ Failed to create channel: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating channel: {e}")
        return None

def main():
    guild_id = create_guild("Moderator Training Ground")
    if not guild_id:
        return

    # Categories and Channels
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

    for cat in structure:
        cat_id = create_channel(guild_id, cat["name"], cat["type"])
        if cat_id:
            for chan in cat["channels"]:
                create_channel(guild_id, chan["name"], chan["type"], parent_id=cat_id)
                time.sleep(0.5)

    print("\n✅ Training Ground setup complete!")
    print(f"Target Guild ID: {guild_id}")

    # Save to a file for the bot to use
    with open("training_ground_config.json", "w") as f:
        json.dump({"guild_id": guild_id}, f)

if __name__ == "__main__":
    main()
