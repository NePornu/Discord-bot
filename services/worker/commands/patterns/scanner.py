import time
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
        logger.info("Pattern scanner loop triggered!")
        try:
            r = await self._get_redis()
            gid = self._guild_id
            found_alerts = []

            # 1. Identify staff to skip
            
            await self.scan_guild(r, gid)
            # 2. Scan Discourse (Synthetic GID 999)
            await self.scan_guild(r, 999)
            
            await self.check_followups()
            
            await r.aclose()
        except Exception as e:
            logger.error(f"Pattern scanner error: {e}")

    async def scan_guild(self, r, gid: int):
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

        # 3. Scan each user (with activity filter and pacing)
        cutoff_ts = int(time.time()) - (48 * 3600)  # Only users active in last 48h
        scanned_count = 0
        skipped_count = 0
        
        for uid in user_ids:
            if uid in staff_ids:
                continue
                
            # Activity filter to save resources
            last_act = await r.get(K_LAST_ACTIVITY(gid, uid))
            if not last_act or int(last_act) < cutoff_ts:
                skipped_count += 1
                continue
                
            try:
                user_alerts = await self.detectors.scan_user(r, gid, uid, now, today)
                found_alerts.extend(user_alerts)
                scanned_count += 1
                
                # Pacing: avoid slamming CPU if scanning many users
                if scanned_count % 5 == 0:
                    await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Error scanning user {uid}: {e}")

        if scanned_count > 0 or skipped_count > 0:
            logger.info(f"Scan stats for gid {gid}: {scanned_count} scanned, {skipped_count} skipped (inactive)")

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
                await self.alerts.send_batched_alerts(uid, alerts, gid=gid)
                for alert in alerts:
                    await self.alerts.mark_alert_sent(r, gid, alert)
                sent_count += len(alerts)
            except Exception as e:
                logger.error(f"Failed to send batched alerts for user {uid}: {e}")

        await r.set(K_LAST_SCAN(gid), str(int(now.timestamp())), ex=86400)

        if sent_count > 0:
            logger.info(f"Pattern scan: {len(user_ids)} users, {sent_count} alerts sent")

    async def check_followups(self):
        r = await self._get_redis()
        try:
            gid = self._guild_id
            prefix = f"pat:followup:{gid}:"
            cursor = "0"
            now_ts = int(time.time())
            
            from .common import K_THREAD, K_LAST_ACTIVITY
            
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"{prefix}*", count=100)
                for k in keys:
                    try:
                        uid = int(k.split(":")[-1])
                        deadline = int(await r.get(k) or 0)
                        
                        if deadline > 0 and now_ts >= deadline:
                            last_act = await r.get(K_LAST_ACTIVITY(gid, uid))
                            if last_act and int(last_act) > (deadline - 48*3600):
                                await r.delete(k)
                                continue
                            
                            thread_id = await r.get(K_THREAD(gid, uid))
                            if thread_id:
                                try:
                                    guild = self.bot.get_guild(gid)
                                    thread = guild.get_thread(int(thread_id))
                                    if thread:
                                        if thread.archived:
                                            await thread.edit(archived=False)
                                        await thread.send(f"🔔 **Připomínka sledování**: Klient <@{uid}> za posledních 48 hodin nenapsal žádnou zprávu. @Moderační tým")
                                except Exception as e:
                                    logger.error(f"Failed to send follow-up reminder for {uid}: {e}")
                            
                            await r.delete(k)
                    except Exception as e:
                        logger.error(f"Error processing followup {k}: {e}")
                
                if cursor == 0 or cursor == "0": break
        finally:
            await r.aclose()

    @pattern_scanner.before_loop
    async def _before_scanner(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)
