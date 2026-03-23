import logging
import asyncio
from datetime import datetime, timezone
import discord
from discord.ext import tasks
from .common import K_LAST_SCAN
from shared.python.config import config

logger = logging.getLogger("PatternDetector")

class PatternScanner:
    def __init__(self, bot, guild_id, redis_getter, detectors, alerts):
        self.bot = bot
        self._guild_id = guild_id
        self._get_redis = redis_getter
        self.detectors = detectors
        self.alerts = alerts
        self.pattern_scanner.start()

    def cog_unload(self):
        self.pattern_scanner.cancel()

    @tasks.loop(minutes=config.PATTERN_SCAN_INTERVAL_MINUTES)
    async def pattern_scanner(self):
        try:
            r = await self._get_redis()
            gid = self._guild_id
            found_alerts = []

            # 1. Identify staff to skip
            staff_ids = set()
            guild = self.bot.get_guild(gid)
            if guild:
                from .common import is_staff
                for member in guild.members:
                    if is_staff(member):
                        staff_ids.add(member.id)
            
            # 2. Collect all known user IDs
            user_ids = set()
            cursor = "0"
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"pat:msg:{gid}:*", count=500)
                for k in keys:
                    parts = k.split(":")
                    if len(parts) >= 4:
                        user_ids.add(int(parts[3]))
                if cursor == 0 or cursor == "0":
                    break

            now = datetime.now(timezone.utc)
            today = now.strftime("%Y%m%d")

            # 3. Scan each user
            for uid in user_ids:
                if uid in staff_ids:
                    continue
                try:
                    user_alerts = await self.detectors.scan_user(r, gid, uid, now, today)
                    found_alerts.extend(user_alerts)
                except Exception as e:
                    logger.error(f"Error scanning user {uid}: {e}")

            # 4. Group patterns
            try:
                group_alerts = await self.detectors.scan_group_patterns(r, gid, now, today, user_ids)
                found_alerts.extend(group_alerts)
            except Exception as e:
                logger.error(f"Error in group pattern scan: {e}")

            # 5. Group alerts by user & check mutes
            from .common import K_MUTE
            user_to_alerts = {}
            for alert in found_alerts:
                # Check for 7-day mute
                if await r.exists(K_MUTE(gid, alert.user_id)):
                    continue

                if await self.alerts.should_send_alert(r, gid, alert):
                    if alert.user_id not in user_to_alerts:
                        user_to_alerts[alert.user_id] = []
                    user_to_alerts[alert.user_id].append(alert)

            # 6. Send batched alerts
            sent_count = 0
            for uid, alerts in user_to_alerts.items():
                try:
                    await self.alerts.send_batched_alerts(uid, alerts)
                    for alert in alerts:
                        await self.alerts.mark_alert_sent(r, gid, alert)
                    sent_count += len(alerts)
                except Exception as e:
                    logger.error(f"Failed to send batched alerts for user {uid}: {e}")

            await r.set(K_LAST_SCAN(gid), str(int(now.timestamp())), ex=86400)
            await r.aclose()

            if sent_count > 0:
                logger.info(f"Pattern scan: {len(user_ids)} users, {sent_count} alerts sent")

        except Exception as e:
            logger.error(f"Pattern scanner error: {e}")

    @pattern_scanner.before_loop
    async def _before_scanner(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(30)
