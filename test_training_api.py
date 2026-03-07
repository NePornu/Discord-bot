
import httpx
import asyncio

async def main():
    token = 'flx_Pw5TId8kChRwm5H1ZSEGsfOYD0sKXX4eg9oE'
    guild_id = '1475546302405693440'
    api_url = 'http://fluxer-api-1:8080/v1'
    
    headers = {
        'Authorization': token,
        'Content-Type': 'application/json'
    }
    
    print(f"Testing connectivity to {api_url}...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{api_url}/guilds/{guild_id}/channels", headers=headers)
            print(f"Status Code: {resp.status_code}")
            if resp.status_code == 200:
                channels = resp.json()
                print(f"Success! Found {len(channels)} channels.")
                # find chat-moderation
                mod_ch = next((c for c in channels if c['name'] == 'chat-moderation'), None)
                if mod_ch:
                    print(f"Found 'chat-moderation' channel: {mod_ch['id']}")
                else:
                    print("Could not find 'chat-moderation' channel!")
            else:
                print(f"Error: {resp.text}")
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())
