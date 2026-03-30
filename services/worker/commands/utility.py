from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import re
from typing import Optional, Union

class EditMessageModal(discord.ui.Modal, title='Upravit zprávu bota'):
    content = discord.ui.TextInput(
        label='Obsah zprávy',
        style=discord.TextStyle.paragraph,
        placeholder='Zadejte nový obsah zprávy...',
        required=True,
        min_length=1,
        max_length=2000,
    )

    def __init__(self, message: discord.Message):
        super().__init__()
        self.message = message
        self.content.default = message.content

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.message.edit(content=self.content.value)
            await interaction.response.send_message(f"✅ Zpráva byla úspěšně upravena: {self.message.jump_url}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Nepodařilo se upravit zprávu: {e}", ephemeral=True)

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Register context menu manually
        self.ctx_menu = app_commands.ContextMenu(
            name="Upravit zprávu",
            callback=self.edit_message_context
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        # Remove context menu when cog is unloaded
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @app_commands.command(name="say", description="Bot odešle zprávu do vybraného kanálu")
    @app_commands.describe(channel="Kanál, kam má bot zprávu odeslat", message="Text zprávy k odeslání")
    @app_commands.checks.has_permissions(administrator=True)
    async def say_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        try:
            await channel.send(message)
            await interaction.response.send_message(f"✅ Zpráva byla odeslána do {channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Nepodařilo se odeslat zprávu: {e}", ephemeral=True)

    @app_commands.command(name="edit", description="Upraví zprávu, kterou bot poslal")
    @app_commands.describe(message_ref="ID zprávy nebo link na zprávu k upravení", new_content="Nový text zprávy (volitelné – jinak se otevře okno)")
    @app_commands.checks.has_permissions(administrator=True)
    async def edit_cmd(self, interaction: discord.Interaction, message_ref: str, new_content: Optional[str] = None):
        # If content provided, update directly
        if new_content:
            await interaction.response.defer(ephemeral=True)
            message = await self.fetch_message_from_ref(interaction, message_ref)
            if not message:
                await interaction.followup.send("❌ Nepodařilo se najít zprávu.", ephemeral=True)
                return
            if message.author != self.bot.user:
                await interaction.followup.send("❌ Tato zpráva nebyla poslána botem.", ephemeral=True)
                return
            await message.edit(content=new_content)
            await interaction.followup.send(f"✅ Zpráva upravena: {message.jump_url}", ephemeral=True)
        else:
            # Interactive mode - show modal
            message = await self.fetch_message_from_ref(interaction, message_ref)
            if not message:
                await interaction.response.send_message("❌ Nepodařilo se najít zprávu.", ephemeral=True)
                return
            if message.author != self.bot.user:
                await interaction.response.send_message("❌ Tato zpráva nebyla poslána botem.", ephemeral=True)
                return
            await interaction.response.send_modal(EditMessageModal(message))

    @app_commands.checks.has_permissions(administrator=True)
    async def edit_message_context(self, interaction: discord.Interaction, message: discord.Message):
        if message.author != self.bot.user:
            await interaction.response.send_message("❌ Tato zpráva nebyla poslána botem.", ephemeral=True)
            return
        await interaction.response.send_modal(EditMessageModal(message))

    @app_commands.command(name="delete", description="Smaže zprávu, kterou bot poslal")
    @app_commands.describe(message_ref="ID zprávy nebo link na zprávu ke smazání")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_cmd(self, interaction: discord.Interaction, message_ref: str):
        await interaction.response.defer(ephemeral=True)
        message = await self.fetch_message_from_ref(interaction, message_ref)
        if not message:
            await interaction.followup.send("❌ Nepodařilo se najít zprávu. Ujisti se, že ID (v tomto kanálu) nebo link je správný.", ephemeral=True)
            return

        if message.author != self.bot.user:
            await interaction.followup.send("❌ Tato zpráva nebyla poslána botem.", ephemeral=True)
            return

        try:
            await message.delete()
            await interaction.followup.send("✅ Zpráva byla úspěšně smazána.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Nepodařilo se smazat zprávu: {e}", ephemeral=True)

    async def fetch_message_from_ref(self, interaction: discord.Interaction, ref: str) -> Optional[discord.Message]:
        # Check if it's a link
        link_match = re.search(r"https://discord\.com/channels/(\d+)/(\d+)/(\d+)", ref)
        if link_match:
            try:
                channel_id = int(link_match.group(2))
                message_id = int(link_match.group(3))
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(channel_id)
                return await channel.fetch_message(message_id)
            except:
                return None
        
        # Check if it's an ID
        if ref.isdigit():
            message_id = int(ref)
            # Try current channel
            try:
                return await interaction.channel.fetch_message(message_id)
            except:
                pass
                
        return None

async def setup(bot):
    await bot.add_cog(Utility(bot))
