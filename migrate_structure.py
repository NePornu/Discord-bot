import json
import requests
import time

# Fluxer Configuration
API_URL = "http://api:8080/v1"
TARGET_GUILD_ID = "1474016949225660417"

# Read Token
with open("migration_token.txt", "r") as f:
    AUTH_TOKEN = f.read().strip()

HEADERS = {
    "Authorization": AUTH_TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

# Read Structure
with open("discord_structure.json", "r") as f:
    structure = json.load(f)

# Mapping Discord Types to Fluxer Types
TYPE_MAP = {
    "category": 4,
    "text": 0,
    "voice": 2,
    "news": 0,
    "forum": 0,
}

id_map = {}

def create_channel(name, type_str, position, parent_id=None, max_retries=5):
    fluxer_type = TYPE_MAP.get(type_str, 0)
    
    payload = {
        "name": name,
        "type": fluxer_type,
        "topic": "Migrated from Discord",
        "parent_id": parent_id,
        "permission_overwrites": []
    }
    
    url = f"{API_URL}/guilds/{TARGET_GUILD_ID}/channels"
    
    for attempt in range(max_retries):
        print(f"Creating channel '{name}' (Type: {type_str}, Parent: {parent_id})...")
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                new_id = data["id"]
                print(f"✅ Created: {new_id}")
                return new_id
            elif resp.status_code == 429:
                retry_data = resp.json()
                retry_after = retry_data.get("retry_after", 10)
                print(f"⏳ Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after + 1)
                continue
            else:
                print(f"❌ Failed: {resp.status_code} - {resp.text}")
                return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    print(f"❌ Max retries exceeded for '{name}'")
    return None

def main():
    print(f"Starting migration to Guild {TARGET_GUILD_ID}...")
    
    # First, check what channels already exist
    print("\n--- Checking existing channels ---")
    resp = requests.get(f"{API_URL}/guilds/{TARGET_GUILD_ID}/channels", headers=HEADERS)
    existing_channels = []
    if resp.status_code == 200:
        existing_channels = resp.json()
        existing_names = {ch["name"] for ch in existing_channels}
        print(f"Found {len(existing_channels)} existing channels: {existing_names}")
    
    # First pass: Create Categories
    print("\n--- Creating Categories ---")
    for category in structure:
        if category["type"] == "category" and category["id"]:
            # Check if already exists
            existing = [ch for ch in existing_channels if ch["name"] == category["name"] and ch["type"] == 4]
            if existing:
                print(f"⏭️ Category '{category['name']}' already exists: {existing[0]['id']}")
                id_map[str(category["id"])] = existing[0]["id"]
                continue
            new_id = create_channel(category["name"], "category", category["position"])
            if new_id:
                id_map[str(category["id"])] = new_id
            time.sleep(1)  # Small delay between requests
    
    # Second pass: Create Channels
    print("\n--- Creating Channels ---")
    # Refresh existing channels
    resp = requests.get(f"{API_URL}/guilds/{TARGET_GUILD_ID}/channels", headers=HEADERS)
    if resp.status_code == 200:
        existing_channels = resp.json()
    
    for category in structure:
        parent_id = None
        if category["id"] and str(category["id"]) in id_map:
            parent_id = id_map[str(category["id"])]
            
        for channel in category["channels"]:
            # Check if already exists
            existing = [ch for ch in existing_channels 
                       if ch["name"] == channel["name"] and ch["type"] != 4 
                       and ch.get("parent_id") == parent_id]
            if existing:
                print(f"⏭️ Channel '{channel['name']}' already exists: {existing[0]['id']}")
                continue
            create_channel(channel["name"], channel["type"], channel["position"], parent_id)
            time.sleep(1)  # Delay between requests to avoid rate limits

    print("\n✅ Migration Completed.")

if __name__ == "__main__":
    main()
