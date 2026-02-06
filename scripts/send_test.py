import os
import requests
import sys

# Load env vars manually since we are running outside docker or need to source them
# For this one-off, I'll hardcode the known values or expect them in env
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "1468607459332456518"

if not BOT_TOKEN:
    print("Error: BOT_TOKEN not set")
    sys.exit(1)

url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
headers = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json"
}
payload = {
    "content": "✅ **Monitoring System is Online**\nI am now monitoring your services. Alerts will appear here."
}

print(f"Sending message to {CHANNEL_ID}...")
response = requests.post(url, headers=headers, json=payload)
print(f"Status: {response.status_code}")
print(response.text)
