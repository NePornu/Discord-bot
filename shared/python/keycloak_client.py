import httpx
import logging
import os

class KeycloakClient:
    def __init__(self):
        self.server_url = os.getenv("KC_INTERNAL_URL", "http://keycloak:8080")
        self.realm = os.getenv("KC_REALM", "nepornu")
        self.username = "admin"
        self.password = os.getenv("KC_ADMIN_PASSWORD", "ejNuURJheY1P0qjBdce+2ekJIxgFYju2")
        self.token = None

    async def _get_token(self):
        url = f"{self.server_url}/realms/master/protocol/openid-connect/token"
        data = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.username,
            "password": self.password,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data)
            if resp.status_code == 200:
                self.token = resp.json()["access_token"]
                return self.token
            else:
                logging.error(f"Failed to get Keycloak token: {resp.text}")
                return None

    async def get_user_groups(self, keycloak_user_id):
        if not self.token:
            await self._get_token()

        url = f"{self.server_url}/admin/realms/{self.realm}/users/{keycloak_user_id}/groups"
        headers = {"Authorization": f"Bearer {self.token}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 401: # Token expired
                await self._get_token()
                headers["Authorization"] = f"Bearer {self.token}"
                resp = await client.get(url, headers=headers)

            if resp.status_code == 200:
                return resp.json()
            else:
                logging.error(f"Failed to get user groups: {resp.text}")
                return []

keycloak_client = KeycloakClient()
