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

    async def get_filters(self, guild_id: int) -> List[dict]:
        r = await get_redis_client()
        val = await r.get(f"automod:filters:{guild_id}")
        await r.close()
        if not val:
            return []
        
        data = json.loads(val)
        # Migration: convert list of strings to list of dicts
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str):
            new_data = []
            for pattern in data:
                new_data.append({
                    "pattern": pattern,
                    "allowed_roles": [],
                    "allowed_channels": [],
                    "whitelist": [],
                    "action": "approve"
                })
            # Save the migrated data
            await self.save_filters(guild_id, new_data)
            return new_data
        
        return data

    async def save_filters(self, guild_id: int, filters: List[dict]):
        r = await get_redis_client()
        await r.set(f"automod:filters:{guild_id}", json.dumps(filters))
        await r.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self.process_automod(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.content == after.content:
            return
        await self.process_automod(after)

    async def process_automod(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        filters = await self.get_filters(message.guild.id)
        if not filters:
            return

        matched_filter = None
        for f_data in filters:
            pattern = f_data["pattern"]
            allowed_roles = f_data.get("allowed_roles", [])
            allowed_channels = f_data.get("allowed_channels", [])

            try:
                matches = list(re.finditer(pattern, message.content, re.IGNORECASE))
                if matches:
                    # Check exemptions
                    is_exempt = False
                    
                    # Check channel
                    if message.channel.id in allowed_channels:
                        is_exempt = True
                    
                    # Check roles
                    if not is_exempt and isinstance(message.author, discord.Member):
                        user_role_ids = [role.id for role in message.author.roles]
                        if any(role_id in allowed_roles for role_id in user_role_ids):
                            is_exempt = True
                    
                    if not is_exempt:
                        # Universal Whitelist - Check if ALL matches are whitelisted
                        whitelist = f_data.get("whitelist", [])
                        if whitelist:
                            is_fully_whitelisted = True
                            content_lower = message.content.lower()
                            for m in matches:
                                # Find surrounding "word" (contiguous non-whitespace)
                                start_idx = message.content.rfind(' ', 0, m.start()) + 1
                                end_idx = message.content.find(' ', m.end())
                                if end_idx == -1: end_idx = len(message.content)
                                word = content_lower[start_idx:end_idx]
                                
                                # If this match isn't covered by ANY whitelisted keyword, fail
                                if not any(w.lower() in word for w in whitelist):
                                    is_fully_whitelisted = False
                                    break
                            
                            if is_fully_whitelisted:
                                is_exempt = True

                    if not is_exempt:
                        matched_filter = f_data
                        break
            except re.error:
                continue

        if matched_filter:
            action = matched_filter.get("action", "approve")
            await self.handle_filtered_message(message, action=action)

    async def handle_filtered_message(self, message: discord.Message, action: str = "approve"):
        # 1. Store message data in Redis for later approval (if not auto-reject)
        if action == "approve":
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

        if action == "auto_reject":
            embed = discord.Embed(
                title="🛡️ AutoMod: Message Auto-Rejected",
                description=message.content,
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Reason", value="Blacklisted link (Auto-Reject)", inline=True)
            embed.set_footer(text=f"Message ID: {message.id}")
            await approval_channel.send(embed=embed)
        else:
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

    @automod.command(name="filter_add", description="Add a regex filter with optional exemptions")
    @app_commands.describe(
        pattern="Regex pattern to filter",
        allowed_roles="Roles that can use this pattern (mentions or IDs, comma separated)",
        allowed_channels="Channels where this pattern is allowed (mentions or IDs, comma separated)",
        whitelist="Keywords that exempt the message from this filter (comma separated)",
        action="Action to take (approve/auto_reject)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Require Approval", value="approve"),
        app_commands.Choice(name="Auto-Reject", value="auto_reject")
    ])
    @commands.has_permissions(manage_guild=True)
    async def filter_add(self, interaction: discord.Interaction, pattern: str, allowed_roles: Optional[str] = None, allowed_channels: Optional[str] = None, whitelist: Optional[str] = None, action: str = "approve"):
        try:
            re.compile(pattern) # Test if valid regex
        except re.error:
            await interaction.response.send_message(f"❌ Invalid regex pattern: `{pattern}`", ephemeral=True)
            return

        # Parse roles
        role_ids = []
        if allowed_roles:
            items = [i.strip() for i in allowed_roles.split(",")]
            for item in items:
                # Extract digits from <@&123...> or just use digits
                match = re.search(r"(\d+)", item)
                if match:
                    role_ids.append(int(match.group(1)))

        # Parse channels
        channel_ids = []
        if allowed_channels:
            items = [i.strip() for i in allowed_channels.split(",")]
            for item in items:
                # Extract digits from <#123...> or just use digits
                match = re.search(r"(\d+)", item)
                if match:
                    channel_ids.append(int(match.group(1)))

        # Parse whitelist
        whitelist_items = []
        if whitelist:
            whitelist_items = [i.strip() for i in whitelist.split(",") if i.strip()]

        filters = await self.get_filters(interaction.guild_id)
        if any(f["pattern"] == pattern for f in filters):
            await interaction.response.send_message(f"⚠️ Pattern already exists.", ephemeral=True)
            return

        filters.append({
            "pattern": pattern,
            "allowed_roles": role_ids,
            "allowed_channels": channel_ids,
            "whitelist": whitelist_items,
            "action": action
        })
        await self.save_filters(interaction.guild_id, filters)
        
        exemption_text = ""
        if role_ids:
            exemption_text += f"\n- Roles: " + ", ".join([f"<@&{rid}>" for rid in role_ids])
        if channel_ids:
            exemption_text += f"\n- Channels: " + ", ".join([f"<#{cid}>" for cid in channel_ids])
        if whitelist_items:
            exemption_text += f"\n- Whitelist: " + ", ".join([f"`{w}`" for w in whitelist_items])
            
        await interaction.response.send_message(f"✅ Pattern added: `{pattern}` (Action: {action}){exemption_text}", ephemeral=True)

    @automod.command(name="filter_list", description="List all regex filters")
    @commands.has_permissions(manage_guild=True)
    async def filter_list(self, interaction: discord.Interaction):
        filters = await self.get_filters(interaction.guild_id)
        if not filters:
            await interaction.response.send_message("📭 No filters set.", ephemeral=True)
            return

        list_lines = []
        for i, f in enumerate(filters):
            pattern = f["pattern"]
            roles = f.get("allowed_roles", [])
            channels = f.get("allowed_channels", [])
            whitelist = f.get("whitelist", [])
            action = f.get("action", "approve")
            
            line = f"{i+1}. `{pattern}` [Action: {action}]"
            exempts = []
            if roles:
                exempt_roles = " ".join([f"<@&{r}>" for r in roles])
                exempts.append(f"Roles: {exempt_roles}")
            if channels:
                exempt_channels = " ".join([f"<#{c}>" for c in channels])
                exempts.append(f"Chans: {exempt_channels}")
            if whitelist:
                whitelist_text = ", ".join([f"`{w}`" for w in whitelist])
                exempts.append(f"Whitelist: {whitelist_text}")
            
            if exempts:
                line += " | Exempted: [" + ", ".join(exempts) + "]"
            list_lines.append(line)

        list_txt = "\n".join(list_lines)
        # Handle message length
        if len(list_txt) > 1900:
            list_txt = list_txt[:1900] + "\n... (truncated)"
            
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
