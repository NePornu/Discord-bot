import requests
import json
import os

API_URL = "http://172.23.0.14:8080/v1"
try:
    with open("/root/discord-bot/migration_token.txt", "r") as f:
        TOKEN = f.read().strip()
except:
    TOKEN = "flx_Pw5TId8kChRwm5H1ZSEGsfOYD0sKXX4eg9oE"

HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}

def join_bot():
    guild_id = "1475546302405693440"
    bot_id = "1227269599951589508"
    
    # Try multiple common endpoints for joining/adding
    endpoints = [
        (f"/guilds/{guild_id}/members/{bot_id}", "PUT", {}),
        (f"/guilds/{guild_id}/members", "POST", {"id": bot_id}),
        (f"/guilds/{guild_id}/bots", "POST", {"id": bot_id}),
        (f"/guilds/{guild_id}/invites", "POST", {}), # Maybe get an invite?
    ]
    
    for path, method, payload in endpoints:
        url = f"{API_URL}{path}"
        print(f"Trying {method} {path}...")
        try:
            if method == "PUT":
                resp = requests.put(url, headers=HEADERS, json=payload)
            elif method == "POST":
                resp = requests.post(url, headers=HEADERS, json=payload)
            
            print(f"  Response: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    join_bot()
