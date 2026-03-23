import time
import logging
from datetime import datetime, timezone
import discord
from .common import K_ALERT, PatternAlert
from shared.python.config import config

logger = logging.getLogger("PatternDetector")

from typing import List, Optional
from .common import K_ALERT, K_MUTE, K_MSG, PatternAlert
from shared.python.redis_client import get_redis_client

class ModeratorAssistantView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="✔ Vyřízeno", style=discord.ButtonStyle.success, custom_id="pat:handled")
    async def mark_handled(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        # Mute user for 7 days
        await r.set(K_MUTE(self.guild_id, self.user_id), "1", ex=7 * 86400)
        await r.close()
        
        # Disable buttons on the original message
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await itx.edit_original_response(view=self)
        await itx.followup.send(f"✅ Uživatel <@{self.user_id}> byl označen jako vyřízený. Po dobu 7 dní nebudou pro tohoto uživatele generovány žádné další automatické alerty.", ephemeral=True)

    @discord.ui.button(label="📊 Aktivita", style=discord.ButtonStyle.secondary, custom_id="pat:activity")
    async def view_activity(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        
        # Get last activity date
        from .common import get_today
        today = get_today()
        
        # This is a bit complex as we store by date. Let's just suggest the command
        # or try to fetch some info if we had a global log.
        # For now, let's provide a quick summary from the last scan result if possible
        # or just point to the check command.
        
        await itx.followup.send(
            f"💡 **Tip:** Pro detailní diagnostiku použijte příkaz `/patterns check user:<@{self.user_id}>`.\n"
            f"V tomto kanále jsou zobrazeny pouze automatické detekce.", 
            ephemeral=True
        )
        await r.close()

class PatternAlerts:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self._guild_id = guild_id
        self._alert_channel = None

    async def get_alert_channel(self) -> discord.TextChannel:
        if self._alert_channel:
            return self._alert_channel
        guild = self.bot.get_guild(self._guild_id)
        if guild:
            self._alert_channel = guild.get_channel(config.PATTERN_ALERT_CHANNEL_ID)
        return self._alert_channel

    async def should_send_alert(self, r, gid: int, alert: PatternAlert) -> bool:
        key = K_ALERT(gid, alert.user_id, alert.pattern_name)
        return not await r.exists(key)

    async def mark_alert_sent(self, r, gid: int, alert: PatternAlert):
        key = K_ALERT(gid, alert.user_id, alert.pattern_name)
        ttl = config.PATTERN_ALERT_COOLDOWN_HOURS * 3600
        await r.set(key, str(int(time.time())), ex=ttl)

    async def send_batched_alerts(self, user_id: int, alerts: List[PatternAlert]):
        if not alerts:
            return
            
        channel = await self.get_alert_channel()
        if not channel:
            logger.warning(f"Alert channel not found for batched alerts")
            return

        guild = self.bot.get_guild(self._guild_id)
        mention = f"<@{user_id}>"
        display_name = f"Uživatel {user_id}"
        avatar_url = None
        
        if guild:
            try:
                member = guild.get_member(user_id)
                if not member:
                    member = await guild.fetch_member(user_id)
                if member:
                    display_name = member.display_name
                    mention = member.mention
                    avatar_url = member.display_avatar.url
            except Exception as e:
                logger.debug(f"Could not fetch member {user_id}: {e}")

        # Determine highest risk level
        risk_levels = [a.risk_level for a in alerts]
        color = 0x3498DB # Info
        if "critical" in risk_levels:
            color = 0xFF0000
        elif "warning" in risk_levels:
            color = 0xFFA500

        embed = discord.Embed(
            title="🎯 Moderator Assistant: Detekce vzorců",
            description=f"U uživatele **{mention}** ({display_name}) byly zachyceny tyto vzorce:",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        for alert in alerts:
            field_name = f"{alert.emoji} {alert.pattern_name}"
            field_val = (
                f"{alert.description}\n"
                f"⚠️ **Úroveň:** {alert.level_label}\n"
                f"💡 **Doporučení:** {alert.recommended_action}"
            )
            embed.add_field(name=field_name, value=field_val, inline=False)

        embed.set_footer(text=f"ID: {user_id} • Metricord Pattern Engine")

        view = ModeratorAssistantView(user_id, self._guild_id)
        
        try:
            await channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Failed to send batched alert: {e}")

    async def send_alert(self, alert: PatternAlert):
        await self.send_batched_alerts(alert.user_id, [alert])
