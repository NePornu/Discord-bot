import requests
import json
import os

API_URL = "http://fluxer-api-1:8080/v1"

# 1. Get tokens
try:
    with open("migration_token.txt", "r") as f:
        USER_TOKEN = f.read().strip()
except Exception as e:
    print(f"❌ Failed to read migration token: {e}")
    exit(1)

BOT_TOKEN = "MTIyNzI2OTU5OTk1MTU4OTUwOA.GsCoHP.OEpQd6iF6thu7cbvnBl3c5-48rIREWgoLEY6MY"

# 2. Get guild ID
try:
    with open("training_ground_config.json", "r") as f:
        config = json.load(f)
        guild_id = config["guild_id"]
except Exception as e:
    print(f"❌ Failed to read config: {e}")
    exit(1)

print(f"Target Guild ID: {guild_id}")

# 3. Get channels to create an invite
headers_user = {
    "Authorization": USER_TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

resp = requests.get(f"{API_URL}/guilds/{guild_id}/channels", headers=headers_user)
if resp.status_code != 200:
    print(f"❌ Failed to get channels: {resp.status_code} {resp.text}")
    exit(1)

channels = resp.json()
first_text_channel = next((c for c in channels if c.get("type", 0) == 0), None)

if not first_text_channel:
    print("❌ No text channels found to create invite.")
    exit(1)

channel_id = first_text_channel["id"]
print(f"Creating invite for channel: {first_text_channel['name']} ({channel_id})")

# 4. Create Invite
payload = {"max_age": 86400, "max_uses": 10, "temporary": False}
resp = requests.post(f"{API_URL}/channels/{channel_id}/invites", headers=headers_user, json=payload)
if resp.status_code != 200:
    print(f"❌ Failed to create invite: {resp.status_code} {resp.text}")
    exit(1)

invite_code = resp.json()["code"]
print(f"✅ Created Invite Code: {invite_code}")

# 5. Bot joins via Invite
headers_bot = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

print("Attempting to join server with Bot Token...")
resp = requests.post(f"{API_URL}/invites/{invite_code}", headers=headers_bot)
if resp.status_code == 200:
    print(f"✅ Bot successfully joined the guild via invite!")
else:
    print(f"❌ Bot failed to join via invite: {resp.status_code} {resp.text}")
    print("Fallback: Attempting to add Bot ID using User Token and PUT /members...")
    
    bot_id = "1227269599951589508"
    add_resp = requests.put(f"{API_URL}/guilds/{guild_id}/members/{bot_id}", headers=headers_user)
    print(f"Fallback response: {add_resp.status_code} {add_resp.text}")

