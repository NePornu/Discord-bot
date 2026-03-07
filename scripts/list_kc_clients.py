import asyncio
import os
import httpx
import sys

sys.path.append('/root/discord-bot')
from shared.keycloak_client import keycloak_client

async def list_clients():
    await keycloak_client._get_token()
    url = f"{keycloak_client.server_url}/admin/realms/{keycloak_client.realm}/clients"
    headers = {"Authorization": f"Bearer {keycloak_client.token}"}
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            clients = resp.json()
            for c in clients:
                print(f"Client: {c.get('clientId')} (ID: {c.get('id')})")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    asyncio.run(list_clients())
