import discord
from discord.ext import commands
import os

# Monkey-patch discord.py to connect to the local Spacebar/Fluxer instance
discord.http.Route.BASE = "http://172.23.0.14:8080/v1"

import aiohttp

# Deep patch aiohttp.ClientSession.request so we can enforce headers globally
original_session_request = aiohttp.ClientSession.request
def patched_session_request(self, method, url, **kwargs):
    headers = kwargs.get('headers', {})
    if hasattr(headers, 'copy'):
        headers = headers.copy()
    headers['X-Forwarded-For'] = '127.0.0.1'
    kwargs['headers'] = headers
    return original_session_request(self, method, url, **kwargs)
aiohttp.ClientSession.request = patched_session_request

original_ws_connect = aiohttp.ClientSession.ws_connect
def patched_ws_connect(self, url, **kwargs):
    headers = kwargs.get('headers', {})
    if hasattr(headers, 'copy'):
        headers = headers.copy()
    headers['X-Forwarded-For'] = '127.0.0.1'
    kwargs['headers'] = headers
    return original_ws_connect(self, url, **kwargs)
aiohttp.ClientSession.ws_connect = patched_ws_connect


class FluxerTrainingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        
        # Bypass discord.py application_info check which Spacebar returns 403 for
        async def fake_http_app_info():
            return {
                "id": "1475834382828204032",
                "name": "Training Bot",
                "icon": None,
                "description": "",
                "bot_public": True,
                "bot_require_code_grant": False,
                "verify_key": "123",
                "flags": 0,
                "summary": "",
                "owner": {
                    "id": "1227269599951589508",
                    "username": "admin",
                    "discriminator": "0000",
                    "avatar": None
                }
            }
        self.http.application_info = fake_http_app_info

    async def setup_hook(self):
        print("Loading training cog...")
        try:
            await self.load_extension("bot.commands.training")
        except Exception as e:
            print(f"Failed to load training cog: {e}")
        
        print("Syncing command tree to Fluxer...")
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} commands.")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    async def on_ready(self):
        print(f"🚀 Fluxer Training Bot Ready! Logged in as {self.user} (ID: {self.user.id})")
        print(f"Connected to {len(self.guilds)} guilds.")
        for g in self.guilds:
            print(f"- {g.name} (ID: {g.id})")

import discord.gateway

# Patch websocket identify payload to prepend Bot explicitly
original_identify = discord.gateway.DiscordWebSocket.identify
async def patched_identify(self):
    from discord.gateway import __dict__ as gw_dict
    payload = {
        'op': self.IDENTIFY,
        'd': {
            'token': f"Bot {self.token}" if not self.token.startswith("Bot ") else self.token,
            'properties': {
                'os': 'linux',
                'browser': 'discord.py',
                'device': 'discord.py',
            },
            'compress': True,
            'large_threshold': 250,
            'v': 9,
        }
    }
    if self.shard_id is not None:
        payload['d']['shard'] = [self.shard_id, self.shard_count]
    if self._initial_features is not None:
        payload['d']['intents'] = getattr(self.call_handlers, 'intents', 0)
        # simplistic bypass
    await self.send_as_json(payload)
discord.gateway.DiscordWebSocket.identify = patched_identify

if __name__ == "__main__":
    bot = FluxerTrainingBot()
    token = "1475834382828204032.X6acgzyFTiuTdPV5dfvW7NEgSMjPVIsdSunMhX1gHTI"
    bot.run(token)
