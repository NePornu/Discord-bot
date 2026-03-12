import time
import logging
from datetime import datetime, timezone
import discord
from .common import K_ALERT, PatternAlert
from shared.python.config import config

logger = logging.getLogger("PatternDetector")

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

    async def send_alert(self, alert: PatternAlert):
        channel = await self.get_alert_channel()
        if not channel:
            logger.warning(f"Alert channel not found for pattern: {alert.pattern_name}")
            return

        embed = discord.Embed(
            title=f"{alert.emoji} {alert.pattern_name}",
            description=alert.description,
            color=alert.color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤 Uživatel", value=f"<@{alert.user_id}>", inline=True)
        embed.add_field(name="⚠️ Úroveň", value=alert.level_label, inline=True)
        embed.add_field(name="💡 Doporučení", value=alert.recommended_action, inline=False)
        embed.set_footer(text="Metricord Pattern Engine")

        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
