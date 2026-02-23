from __future__ import annotations

import re
import json
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List, Dict
from shared.redis_client import get_redis_client

class AutoModCustom(commands.Cog):
    """Custom AutoMod with Regex filtering and Moderator Approval."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.approval_channel_id = 882936285738704897  # Default channel from user request

    async def get_redis_data(self, key: str) -> Optional[str]:
        r = await get_redis_client()
        val = await r.get(key)
        await r.close()
        return val

    async def set_redis_data(self, key: str, value: str):
        r = await get_redis_client()
        await r.set(key, value)
        await r.close()

    async def get_filters(self, guild_id: int) -> List[str]:
        r = await get_redis_client()
        val = await r.get(f"automod:filters:{guild_id}")
        await r.close()
        return json.loads(val) if val else []

    async def save_filters(self, guild_id: int, filters: List[str]):
        r = await get_redis_client()
        await r.set(f"automod:filters:{guild_id}", json.dumps(filters))
        await r.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        filters = await self.get_filters(message.guild.id)
        if not filters:
            return

        matched = False
        for pattern in filters:
            try:
                if re.search(pattern, message.content, re.IGNORECASE):
                    matched = True
                    break
            except re.error:
                continue

        if matched:
            await self.handle_filtered_message(message)

    async def handle_filtered_message(self, message: discord.Message):
        # 1. Store message data in Redis for later approval
        r = await get_redis_client()
        msg_data = {
            "content": message.content,
            "author_id": message.author.id,
            "author_name": message.author.name,
            "author_avatar": str(message.author.display_avatar.url),
            "channel_id": message.channel.id,
            "guild_id": message.guild.id
        }
        # Use a temporary key with TTL
        await r.setex(f"automod:pending:{message.id}", 86400, json.dumps(msg_data))
        await r.close()

        # 2. Delete the original message
        try:
            await message.delete()
        except discord.Forbidden:
            pass # Lack of permissions

        # 3. Send approval request to the designated channel
        approval_channel = self.bot.get_channel(self.approval_channel_id)
        if not approval_channel:
            return

        embed = discord.Embed(
            title="🛡️ AutoMod: Message Awaiting Approval",
            description=message.content,
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.set_footer(text=f"Message ID: {message.id}")

        view = ApprovalView(message.id, self)
        await approval_channel.send(embed=embed, view=view)

    # --- Slash Commands ---
    automod = app_commands.Group(name="automod", description="Custom AutoMod Management")

    @automod.command(name="filter_add", description="Add a regex filter")
    @app_commands.describe(pattern="Regex pattern to filter")
    @commands.has_permissions(manage_guild=True)
    async def filter_add(self, interaction: discord.Interaction, pattern: str):
        try:
            re.compile(pattern) # Test if valid regex
        except re.error:
            await interaction.response.send_message(f"❌ Invalid regex pattern: `{pattern}`", ephemeral=True)
            return

        filters = await self.get_filters(interaction.guild_id)
        if pattern in filters:
            await interaction.response.send_message(f"⚠️ Pattern already exists.", ephemeral=True)
            return

        filters.append(pattern)
        await self.save_filters(interaction.guild_id, filters)
        await interaction.response.send_message(f"✅ Pattern added: `{pattern}`", ephemeral=True)

    @automod.command(name="filter_list", description="List all regex filters")
    @commands.has_permissions(manage_guild=True)
    async def filter_list(self, interaction: discord.Interaction):
        filters = await self.get_filters(interaction.guild_id)
        if not filters:
            await interaction.response.send_message("📭 No filters set.", ephemeral=True)
            return

        list_txt = "\n".join([f"{i+1}. `{f}`" for i, f in enumerate(filters)])
        await interaction.response.send_message(f"🛡️ **Current Filters:**\n{list_txt}", ephemeral=True)

    @automod.command(name="filter_remove", description="Remove a regex filter")
    @app_commands.describe(index="Index of the filter to remove (from /automod filter_list)")
    @commands.has_permissions(manage_guild=True)
    async def filter_remove(self, interaction: discord.Interaction, index: int):
        filters = await self.get_filters(interaction.guild_id)
        if index < 1 or index > len(filters):
            await interaction.response.send_message(f"❌ Invalid index `{index}`.", ephemeral=True)
            return

        removed = filters.pop(index - 1)
        await self.save_filters(interaction.guild_id, filters)
        await interaction.response.send_message(f"✅ Removed pattern: `{removed}`", ephemeral=True)

class ApprovalView(discord.ui.View):
    def __init__(self, message_id: int, cog: AutoModCustom):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.cog = cog

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id=f"automod_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        r = await get_redis_client()
        data_raw = await r.get(f"automod:pending:{self.message_id}")
        if not data_raw:
            await interaction.followup.send("⚠️ Message data expired or not found.", ephemeral=True)
            await r.close()
            return
        
        data = json.loads(data_raw)
        channel = self.cog.bot.get_channel(data["channel_id"])
        
        if not channel:
            await interaction.followup.send("❌ Target channel no longer exists.", ephemeral=True)
            await r.close()
            return

        # re-post using Webhook
        try:
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="AutoMod Restorer")
            if not webhook:
                webhook = await channel.create_webhook(name="AutoMod Restorer")
            
            await webhook.send(
                content=data["content"],
                username=data["author_name"],
                avatar_url=data["author_avatar"]
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to restore message: {e}", ephemeral=True)
            await r.close()
            return

        await r.delete(f"automod:pending:{self.message_id}")
        await r.close()

        # Update the approval message
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Message Approved"
        embed.set_footer(text=f"Approved by {interaction.user}")
        await interaction.message.edit(embed=embed, view=None)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id=f"automod_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        r = await get_redis_client()
        await r.delete(f"automod:pending:{self.message_id}")
        await r.close()

        # Update the approval message
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Message Rejected"
        embed.set_footer(text=f"Rejected by {interaction.user}")
        await interaction.message.edit(embed=embed, view=None)

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModCustom(bot))
