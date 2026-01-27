

from __future__ import annotations

import re
from typing import Optional

import discord
from discord import app_commands, Interaction
from discord.ext import commands

CHANNEL_MENTION_RE = re.compile(r"<#(\d+)>")


class EchoCog(commands.Cog):
    """Jednoduchý echo/say příkaz s podporou kanálů a příloh."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_channel(self, guild: Optional[discord.Guild], channel_input: Optional[str]) -> Optional[discord.TextChannel]:
        """Najde kanál podle ID, názvu nebo <#mention>."""
        if not guild or not channel_input:
            return None
        
        channel_input = channel_input.strip()
        
        
        match = CHANNEL_MENTION_RE.search(channel_input)
        if match:
            ch = guild.get_channel(int(match.group(1)))
            return ch if isinstance(ch, discord.TextChannel) else None
        
        
        if channel_input.isdigit():
            ch = guild.get_channel(int(channel_input))
            return ch if isinstance(ch, discord.TextChannel) else None
        
        
        for ch in guild.text_channels:
            if ch.name.lower() == channel_input.lower():
                return ch
        
        return None

    async def _download_files(self, *attachments: Optional[discord.Attachment]) -> list[discord.File]:
        """Stáhne až 10 příloh."""
        files = []
        for att in (a for a in attachments if a):
            if len(files) >= 10:
                break
            try:
                files.append(await att.to_file())
            except:
                continue
        return files

    @commands.hybrid_command(
        name="echo",
        aliases=["say", "repeat"],
        description="Zopakuje zprávu"
    )
    @app_commands.describe(
        text="Text k zopakování",
        channel="Cílový kanál (volitelné)",
        hide="Skrýt odpověď (pouze slash)",
        no_mentions="Zakázat @mentions",
        file1="Příloha 1",
        file2="Příloha 2",
        file3="Příloha 3",
    )
    async def echo(
        self,
        ctx: commands.Context,
        text: str,
        channel: Optional[str] = None,
        hide: bool = False,
        no_mentions: bool = True,
        file1: Optional[discord.Attachment] = None,
        file2: Optional[discord.Attachment] = None,
        file3: Optional[discord.Attachment] = None,
    ):
        """Hlavní echo příkaz."""
        is_slash = ctx.interaction is not None
        
        
        if not text.strip():
            if is_slash:
                await ctx.send("❌ Text nemůže být prázdný.", ephemeral=True)
            else:
                await ctx.send("❌ Text nemůže být prázdný.", delete_after=3)
            return
        
        
        target = self._get_channel(ctx.guild, channel)
        
        
        if is_slash:
            files = await self._download_files(file1, file2, file3)
        else:
            files = await self._download_files(*ctx.message.attachments)
        
        
        mentions = discord.AllowedMentions.none() if no_mentions else discord.AllowedMentions.all()
        
        
        if not is_slash:
            dest = target or ctx.channel
            try:
                await dest.send(text, files=files, allowed_mentions=mentions)
                await ctx.message.delete()
            except discord.Forbidden:
                await ctx.send("❌ Nemám oprávnění.", delete_after=3)
            except Exception as e:
                await ctx.send(f"❌ Chyba: {e}", delete_after=5)
            return
        
        
        try:
            if target and target.id != ctx.channel.id:
                
                await target.send(text, files=files, allowed_mentions=mentions)
                await ctx.send(f"✅ Odesláno do {target.mention}", ephemeral=True)
            else:
                
                await ctx.send(text, files=files, allowed_mentions=mentions, ephemeral=hide)
        except discord.Forbidden:
            await ctx.send("❌ Nemám oprávnění do tohoto kanálu.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Chyba: {e}", ephemeral=True)

    @app_commands.command(name="say", description="Alias pro /echo")
    @app_commands.describe(
        text="Text k odeslání",
        channel="Cílový kanál",
        hide="Skrýt odpověď",
        no_mentions="Zakázat @mentions",
        file1="Příloha 1",
        file2="Příloha 2",
        file3="Příloha 3",
    )
    async def say(
        self,
        itx: Interaction,
        text: str,
        channel: Optional[str] = None,
        hide: bool = False,
        no_mentions: bool = True,
        file1: Optional[discord.Attachment] = None,
        file2: Optional[discord.Attachment] = None,
        file3: Optional[discord.Attachment] = None,
    ):
        """Standalone /say příkaz."""
        
        if not text.strip():
            await itx.response.send_message("❌ Text nemůže být prázdný.", ephemeral=True)
            return
        
        
        await itx.response.defer(ephemeral=hide)
        
        
        target = self._get_channel(itx.guild, channel)
        
        
        files = await self._download_files(file1, file2, file3)
        
        
        mentions = discord.AllowedMentions.none() if no_mentions else discord.AllowedMentions.all()
        
        try:
            if target and target.id != itx.channel_id:
                
                await target.send(text, files=files, allowed_mentions=mentions)
                await itx.followup.send(f"✅ Odesláno do {target.mention}", ephemeral=True)
            else:
                
                await itx.followup.send(text, files=files, allowed_mentions=mentions, ephemeral=hide)
        except discord.Forbidden:
            await itx.followup.send("❌ Nemám oprávnění.", ephemeral=True)
        except Exception as e:
            await itx.followup.send(f"❌ Chyba: {e}", ephemeral=True)

    @echo.autocomplete("channel")
    @say.autocomplete("channel")
    async def channel_autocomplete(self, itx: Interaction, current: str):
        """Autocomplete pro výběr kanálu."""
        if not itx.guild:
            return []
        
        current = current.lower()
        choices = []
        
        for ch in itx.guild.text_channels:
            if not current or current in ch.name.lower():
                choices.append(app_commands.Choice(name=f"#{ch.name}", value=f"<#{ch.id}>"))
                if len(choices) >= 25:
                    break
        
        return choices


async def setup(bot: commands.Bot):
    await bot.add_cog(EchoCog(bot))
