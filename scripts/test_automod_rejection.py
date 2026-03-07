import asyncio
import unittest
from unittest.mock import MagicMock, patch
import discord
import json
import sys
import os

# Add bot directory to path
sys.path.append("/root/discord-bot")

from bot.commands.automod_custom import AutoModCustom

async def mock_coro(return_value=None):
    return return_value

class TestAutoModRejection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = MagicMock()
        self.cog = AutoModCustom(self.bot)
        self.guild_id = 123
        
    async def test_auto_reject_logic(self):
        # Mock Redis data
        self.cog.get_filters = MagicMock(return_value=mock_coro([{
            "pattern": r"(?:https?://)?(?:[^/\s]+\.)?(pornhub\.com)(?:\/|\s|$)",
            "allowed_roles": [],
            "allowed_channels": [],
            "whitelist": [],
            "action": "auto_reject"
        }]))
        
        # Mock message
        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.guild.id = self.guild_id
        message.content = "Check this out: https://www.pornhub.com/video"
        message.channel.id = 456
        message.channel.mention = "#test-channel"
        message.author.id = 789
        message.author.name = "TestUser"
        message.author.display_avatar.url = "http://avatar.url"
        message.delete = MagicMock(return_value=mock_coro())
        
        # Mock approval channel
        approval_channel = MagicMock()
        approval_channel.send = MagicMock(return_value=mock_coro())
        self.bot.get_channel.return_value = approval_channel
        
        # Run on_message
        await self.cog.on_message(message)
        
        # Verify
        message.delete.assert_called_once()
        approval_channel.send.assert_called_once()
        args, kwargs = approval_channel.send.call_args
        embed = kwargs.get('embed')
        self.assertEqual(embed.title, "🛡️ AutoMod: Message Auto-Rejected")
        print("✅ Auto-reject test passed!")

    async def test_approve_logic(self):
        # Mock Redis data
        self.cog.get_filters = MagicMock(return_value=mock_coro([{
            "pattern": r"badword",
            "allowed_roles": [],
            "allowed_channels": [],
            "whitelist": [],
            "action": "approve"
        }]))
        
        # Mock message
        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.guild.id = self.guild_id
        message.content = "this is a badword"
        message.channel.id = 456
        message.channel.mention = "#test-channel"
        message.author.id = 789
        message.author.name = "TestUser"
        message.author.display_avatar.url = "http://avatar.url"
        message.delete = MagicMock(return_value=mock_coro())
        
        # Mock approval channel
        approval_channel = MagicMock()
        approval_channel.send = MagicMock(return_value=mock_coro())
        self.bot.get_channel.return_value = approval_channel
        
        # Mock Redis client
        with patch('shared.redis_client.get_redis_client') as mock_redis:
            r = MagicMock()
            r.setex = MagicMock(return_value=mock_coro())
            r.close = MagicMock(return_value=mock_coro())
            mock_redis.return_value = mock_coro(r)
            
            # Run on_message
            await self.cog.on_message(message)
        
        # Verify
        message.delete.assert_called_once()
        approval_channel.send.assert_called_once()
        args, kwargs = approval_channel.send.call_args
        embed = kwargs.get('embed')
        self.assertEqual(embed.title, "🛡️ AutoMod: Message Awaiting Approval")
        self.assertIsNotNone(kwargs.get('view'))
        print("✅ Approval test passed!")

if __name__ == "__main__":
    asyncio.run(unittest.main(argv=['first-arg-is-ignored'], exit=False))

if __name__ == "__main__":
    asyncio.run(unittest.main(argv=['first-arg-is-ignored'], exit=False))
