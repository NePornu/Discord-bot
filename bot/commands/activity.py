

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
from datetime import datetime, timedelta, date
import redis.asyncio as redis
import math
from collections import defaultdict
import re
import json










SESSION_TIMEOUT = 900  
MIN_SESSION_TIME = 60 

LEAD_IN_BASE = 180.0  
LEAD_IN_CHAR = 1.0    
LEAD_IN_REPLY = 60.0  

import os
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

class ActivityMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
        self.r = redis.Redis(connection_pool=self.pool)

    async def cog_unload(self):
        await self.pool.disconnect()

    async def get_action_weights(self) -> dict:
        """Fetch action weights from Redis or use defaults."""
        defaults = {
            "bans": 300, "kicks": 180, "timeouts": 180, "unbans": 120, 
            "verifications": 120, "msg_deleted": 60, "role_updates": 30,
            "chat_time": 1, "voice_time": 1
        }
        
        try:
            stored = await self.r.hgetall("config:action_weights")
            if stored:
                for k, v in stored.items():
                    if k in defaults:
                        defaults[k] = int(v)
        except Exception as e:
            print(f"Error fetching weights: {e}")
        
        return defaults

    def _get_today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _timestamp_to_day(self, ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

    def _k_state(self, gid: int, uid: int, key: str) -> str:
        return f"activity:state:{gid}:{uid}:{key}"

    async def _update_user_info(self, user: discord.Union[discord.Member, discord.User]):
        """Cache user info in Redis for Dashboard."""
        if user.bot: return
        key = f"user:info:{user.id}"
        
        
        
        name = user.display_name
        avatar = user.display_avatar.url
        
        
        roles = ""
        if isinstance(user, discord.Member):
            roles = ",".join(str(r.id) for r in user.roles)
        
        async with self.r.pipeline() as pipe:
            pipe.hset(key, mapping={"name": name, "avatar": avatar, "roles": roles})
            pipe.expire(key, 604800) 
            await pipe.execute()

    
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Logged in as {self.bot.user} (ID: {self.bot.user.id})")
        self.usage_loop.start()

    @tasks.loop(minutes=1.0)
    async def usage_loop(self):
        
        await self._sync_bot_guilds()
        
        now = time.time()
        

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self._sync_bot_guilds()
        
    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self._sync_bot_guilds()

    async def _sync_bot_guilds(self):
        """Sync list of guilds the bot is in to Redis."""
        try:
            guild_ids = [str(g.id) for g in self.bot.guilds]
            if guild_ids:
                await self.r.delete("bot:guilds") 
                await self.r.sadd("bot:guilds", *guild_ids)
            print(f"Synced {len(guild_ids)} guilds to Redis")
        except Exception as e:
            print(f"Error syncing bot guilds: {e}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        
        
        
        
        
        
        key = f"events:msg:{message.guild.id}:{message.author.id}"
        ts = message.created_at.timestamp()
        event_data = json.dumps({
            "mid": message.id,
            "len": len(message.content),
            "reply": message.reference is not None
        })
        
        await self.r.zadd(key, {event_data: ts})
        await self._update_user_info(message.author)


    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        
        
        await self._update_user_info(member)
        
        gid = member.guild.id
        uid = member.id
        now = time.time()
        k_voice = self._k_state(gid, uid, "voice_start")

        is_in = after.channel is not None
        was_in = before.channel is not None
        
        if is_in and not was_in:
            
            await self.r.set(k_voice, now)
        elif was_in and not is_in:
            
            start_str = await self.r.get(k_voice)
            if start_str:
                start = float(start_str)
                duration = now - start
                if duration > 0:
                    
                    lock_key = f"lock:voice:{uid}:{int(start)}"
                    if await self.r.set(lock_key, "1", ex=60, nx=True):
                        
                        key = f"events:voice:{gid}:{uid}"
                        event_data = json.dumps({"duration": int(duration), "ts": int(start)})
                        await self.r.zadd(key, {event_data: start})
                await self.r.delete(k_voice)

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        if not entry.guild or not entry.user or entry.user.bot: return
        
        gid = entry.guild.id
        uid = entry.user.id
        ts = entry.created_at.timestamp()
        
        action_type = None
        
        if entry.action == discord.AuditLogAction.ban:
            action_type = "ban"
        elif entry.action == discord.AuditLogAction.kick:
            action_type = "kick"
        elif entry.action == discord.AuditLogAction.unban:
            action_type = "unban"
        elif entry.action == discord.AuditLogAction.member_update:
            
            if hasattr(entry.after, "timed_out_until") and entry.after.timed_out_until:
                action_type = "timeout"
        elif entry.action == discord.AuditLogAction.member_role_update:
            action_type = "role_update"
        elif entry.action == discord.AuditLogAction.message_delete:
            action_type = "msg_delete"
            
        if action_type:
            
            key = f"events:action:{gid}:{uid}"
            event_data = json.dumps({"type": action_type, "id": entry.id})
            await self.r.zadd(key, {event_data: ts})
            await self._update_user_info(entry.user)

    
    def fmt_time(self, seconds: float) -> str:
        if seconds < 60: return f"{int(seconds)}s"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0: return f"{h}h {m}m"
        return f"{m}m"

    async def get_daily_stats(self, gid: int, uid: int, day: date) -> dict:
        """
        Get daily stats for a user on a specific day.
        Uses cached value if version matches, otherwise recalculates from raw events.
        """
        day_str = day.strftime("%Y-%m-%d")
        cache_key = f"stats:day:{day_str}:{gid}:{uid}"
        
        
        cached_version = await self.r.hget(cache_key, "_version")
        current_version = await self.r.get("config:weights_version") or "0"
        
        if cached_version == current_version:
            
            stats = await self.r.hgetall(cache_key)
            
            return {k: float(v) if k != "_version" else v for k, v in stats.items()}
        
        
        weights = await self.get_action_weights()
        
        
        from datetime import time as dt_time
        day_start = datetime.combine(day, dt_time(0, 0, 0)).timestamp()
        day_end = datetime.combine(day, dt_time(23, 59, 59)).timestamp()
        
        stats = defaultdict(float)
        
        
        msg_key = f"events:msg:{gid}:{uid}"
        messages = await self.r.zrangebyscore(msg_key, day_start, day_end)
        
        for msg_json in messages:
            msg_data = json.loads(msg_json)
            stats["messages"] += 1
            stats["chat_time"] += msg_data["len"] * weights.get("chat_time", 1)
            
            
        
        
        voice_key = f"events:voice:{gid}:{uid}"
        voice_sessions = await self.r.zrangebyscore(voice_key, day_start, day_end)
        
        for vs_json in voice_sessions:
            vs_data = json.loads(vs_json)
            stats["voice_time"] += vs_data["duration"] * weights.get("voice_time", 1)
        
        
        action_key = f"events:action:{gid}:{uid}"
        actions = await self.r.zrangebyscore(action_key, day_start, day_end)
        
        for action_json in actions:
            action_data = json.loads(action_json)
            action_type = action_data["type"]
            
            
            metric_map = {
                "ban": "bans", "kick": "kicks", "timeout": "timeouts",
                "unban": "unbans", "role_update": "role_updates",
                "msg_delete": "msg_deleted"
            }
            
            metric = metric_map.get(action_type, action_type + "s")
            stats[metric] += 1
        
        
        cache_data = dict(stats)
        cache_data["_version"] = current_version
        await self.r.hset(cache_key, mapping={k: str(v) for k, v in cache_data.items()})
        
        return dict(stats)

    
    act_group = app_commands.Group(name="activity", description="Sledování aktivity moderátorů")

    @act_group.command(name="sync_names", description="ADMIN: Synchronizuje jména a ROLE členů do databáze.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_names(self, itx: discord.Interaction):
        await itx.response.defer()
        
        
        roles_key = f"guild:roles:{itx.guild.id}"
        role_map = {str(r.id): r.name for r in itx.guild.roles if r.name != "@everyone"}
        
        async with self.r.pipeline() as pipe:
            pipe.delete(roles_key)
            if role_map:
                pipe.hset(roles_key, mapping=role_map)
            await pipe.execute()
            
        
        count = 0
        for member in itx.guild.members:
            if not member.bot:
                await self._update_user_info(member)
                count += 1
                
        await itx.followup.send(f"✅ Synchronizováno **{count}** členů a **{len(role_map)}** rolí.")

    @act_group.command(name="stats", description="Zobrazí statistiky (lze filtrovat datem).")
    @app_commands.describe(
        user="Uživatel (default: ty)",
        after="Od data (DD-MM-YYYY)",
        before="Do data (DD-MM-YYYY)"
    )
    async def stats(self, itx: discord.Interaction, user: discord.Member = None, after: str = None, before: str = None):
        await itx.response.defer()
        if not user: user = itx.user
        gid = itx.guild.id
        uid = user.id
        
        
        await self._update_user_info(user)
        
        
        d_after = None
        d_before = None
        date_info = "Celková historie"
        
        try:
            if after:
                d_after = datetime.strptime(after, "%d-%m-%Y").date()
            if before:
                d_before = datetime.strptime(before, "%d-%m-%Y").date()
            
            if d_after and d_before:
                date_info = f"{d_after.strftime('%d.%m.%Y')} — {d_before.strftime('%d.%m.%Y')}"
            elif d_after:
                date_info = f"Od {d_after.strftime('%d.%m.%Y')}"
            elif d_before:
                date_info = f"Do {d_before.strftime('%d.%m.%Y')}"
        except ValueError:
            await itx.followup.send("❌ Špatný formát data. Použij `DD-MM-YYYY` (např. 01-01-2025).")
            return

        from collections import defaultdict
        from datetime import time as dt_time
        data = defaultdict(float)
        
        
        start_day = d_after if d_after else date(2015, 1, 1)  
        end_day = d_before if d_before else date.today()
        
        ts_start = datetime.combine(start_day, dt_time(0, 0, 0)).timestamp()
        ts_end = datetime.combine(end_day, dt_time(23, 59, 59)).timestamp()
        
        weights = await self.get_action_weights()
        
        
        msg_key = f"events:msg:{gid}:{uid}"
        messages = await self.r.zrangebyscore(msg_key, ts_start, ts_end)
        for msg_json in messages:
            msg_data = json.loads(msg_json)
            data["messages"] += 1
            data["chat_time"] += msg_data["len"] * weights.get("chat_time", 1)
        
        
        voice_key = f"events:voice:{gid}:{uid}"
        voice_sessions = await self.r.zrangebyscore(voice_key, ts_start, ts_end)
        for vs_json in voice_sessions:
            vs_data = json.loads(vs_json)
            data["voice_time"] += vs_data["duration"] * weights.get("voice_time", 1)
        
        
        action_key = f"events:action:{gid}:{uid}"
        actions = await self.r.zrangebyscore(action_key, ts_start, ts_end)
        metric_map = {
            "ban": "bans", "kick": "kicks", "timeout": "timeouts",
            "unban": "unbans", "role_update": "role_updates",
            "msg_delete": "msg_deleted", "verification": "verifications"
        }
        for action_json in actions:
            action_data = json.loads(action_json)
            action_type = action_data["type"]
            metric = metric_map.get(action_type, action_type + "s")
            data[metric] += 1
        
        
        today = date.today()
        include_pending = True
        if d_before and d_before < today: include_pending = False
        if d_after and d_after > today: include_pending = False
        
        if include_pending:
            now = time.time()
            
            k_cs = self._k_state(gid, uid, "chat_start")
            k_cl = self._k_state(gid, uid, "chat_last")
            cs = await self.r.get(k_cs)
            cl = await self.r.get(k_cl)
            if cs and cl and (now - float(cl) < SESSION_TIMEOUT):
                
                data["chat_time"] += (float(cl) - float(cs))
            
            k_vs = self._k_state(gid, uid, "voice_start")
            vs = await self.r.get(k_vs)
            if vs:
                data["voice_time"] += (now - float(vs))

        
        chat_t = data["chat_time"]
        voice_t = data["voice_time"]
        msgs = int(data["messages"])
        
        ACTION_WEIGHTS = await self.get_action_weights()
        action_time = 0
        for m, w in ACTION_WEIGHTS.items():
            action_time += (data[m] * w)
            
        total_time = chat_t + voice_t + action_time
        
        
        e = discord.Embed(title=f"📊 Aktivita: {user.display_name}", description=f"📅 **Období:** {date_info}", color=discord.Color.blue())
        e.set_thumbnail(url=user.display_avatar.url)
        
        e.add_field(name="💬 Chat Time", value=self.fmt_time(chat_t), inline=True)
        e.add_field(name="🎙️ Voice Time", value=self.fmt_time(voice_t), inline=True)
        e.add_field(name="🛠️ Action Time", value=self.fmt_time(action_time), inline=True)
        e.add_field(name="📩 Zpráv", value=str(msgs), inline=True)
        
        bans = int(data["bans"])
        kicks = int(data["kicks"])
        timeouts = int(data["timeouts"])
        dels = int(data["msg_deleted"])
        roles = int(data["role_updates"])
        unbans = int(data["unbans"])
        verifs = int(data["verifications"])
        
        e.add_field(name="🔨 Bany", value=str(bans), inline=True)
        e.add_field(name="👢 Kicky", value=str(kicks), inline=True)
        e.add_field(name="🤐 Timeouts", value=str(timeouts), inline=True)
        e.add_field(name="🗑️ Smazáno", value=str(dels), inline=True)
        e.add_field(name="🎭 Role", value=str(roles), inline=True)
        e.add_field(name="🔓 Unbany", value=str(unbans), inline=True)
        e.add_field(name="✅ Verifikace", value=str(verifs), inline=True)
        
        total_h = total_time / 3600
        e.add_field(name="⏱️ Celkový vážený čas", value=f"**{total_h:.1f} hodin**", inline=False)
        
        await itx.followup.send(embed=e)

    @act_group.command(name="leaderboard", description="TOP 10 nejaktivnějších (s filtrem data).")
    @app_commands.describe(after="Od data (DD-MM-YYYY)", before="Do data (DD-MM-YYYY)")
    async def leaderboard(self, itx: discord.Interaction, after: str = None, before: str = None):
        await itx.response.defer()
        gid = itx.guild.id
        
        d_after = None
        d_before = None
        date_info = "Celková historie"
        try:
            if after: d_after = datetime.strptime(after, "%d-%m-%Y").date()
            if before: d_before = datetime.strptime(before, "%d-%m-%Y").date()
            
            if d_after and d_before:
                date_info = f"{d_after.strftime('%d.%m.%Y')} — {d_before.strftime('%d.%m.%Y')}"
            elif d_after:
                date_info = f"Od {d_after.strftime('%d.%m.%Y')}"
            elif d_before:
                date_info = f"Do {d_before.strftime('%d.%m.%Y')}"
        except ValueError:
            await itx.followup.send("❌ Špatný formát data.")
            return

        user_scores = defaultdict(float) 
        
        
        ACTION_WEIGHTS = await self.get_action_weights()
        
        
        active_users = set()
        for pattern in [f"events:msg:{gid}:*", f"events:voice:{gid}:*", f"events:action:{gid}:*"]:
            async for key in self.r.scan_iter(pattern):
                parts = key.split(":")
                if len(parts) == 4:
                    active_users.add(int(parts[3]))
        
        
        current_day = d_after if d_after else (date.today() - timedelta(days=365))
        end_day = d_before if d_before else date.today()
        
        while current_day <= end_day:
            for uid in active_users:
                daily = await self.get_daily_stats(gid, uid, current_day)
                
                
                chat_t = daily.get("chat_time", 0)
                voice_t = daily.get("voice_time", 0)
                
                action_t = 0
                for action_metric in ["bans", "kicks", "timeouts", "unbans", "verifications", "msg_deleted", "role_updates"]:
                    action_t += daily.get(action_metric, 0) * ACTION_WEIGHTS.get(action_metric, 0)
                
                user_scores[uid] += (chat_t + voice_t + action_t)
            
            current_day += timedelta(days=1)

        sorted_users = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        
        desc = []
        for i, (uid, sec) in enumerate(sorted_users, 1):
            desc.append(f"**{i}.** <@{uid}> — `{self.fmt_time(sec)}`")
            
        if not desc: desc = ["Žádná data pro toto období."]
        
        e = discord.Embed(title=f"🏆 Leaderboard ({date_info})", description="\n".join(desc), color=discord.Color.gold())
        e.set_footer(text="Řazeno podle váženého času")
        await itx.followup.send(embed=e)

    @act_group.command(name="backfill", description="ADMIN: Resetuje a přepočítá data do denních statistik.")
    @app_commands.describe(days="Počet dní zpětně (např. 365).")
    @app_commands.checks.has_permissions(administrator=True)
    async def backfill(self, itx: discord.Interaction, days: int = 30):
        await itx.response.defer(thinking=True)
        gid = itx.guild.id
        
        
        await itx.followup.send("🗑️ Mazání staré databáze aktivity...")
        
        keys = []
        
        async for k in self.r.scan_iter(f"activity:stats:{gid}:*"): keys.append(k)
        async for k in self.r.scan_iter(f"activity:day:*:{gid}:*"): keys.append(k)
        
        if keys:
            chunk_size = 500
            for i in range(0, len(keys), chunk_size):
                await self.r.delete(*keys[i:i+chunk_size])
                
        
        discord_epoch = datetime(2015, 1, 1)
        limit_date = datetime.now() - timedelta(days=days)
        if limit_date < discord_epoch: limit_date = discord_epoch
        
        await itx.followup.send(f"⏳ Začínám Backfill od {limit_date.date()}... (Režim: 3min Base + Chars)")
        
        
        msg_count = 0
        user_messages = defaultdict(list)  
        BATCH_SIZE = 10000  
        
        for channel in itx.guild.text_channels:
            try:
                async for msg in channel.history(limit=None, after=limit_date):
                    if not msg.author.bot:
                        ts = msg.created_at.timestamp()
                        length = len(msg.content)
                        is_reply = (msg.reference is not None)
                        
                        user_messages[msg.author.id].append((ts, length, is_reply))
                        msg_count += 1
                        
                        
                        await self._update_user_info(msg.author)
                        
                        
                        if msg_count % BATCH_SIZE == 0:
                            
                            for uid, messages in user_messages.items():
                                key = f"events:msg:{gid}:{uid}"
                                mapping = {}
                                for ts, length, is_reply in messages:
                                    event_data = json.dumps({"len": length, "reply": is_reply})
                                    mapping[event_data] = ts
                                
                                if mapping:
                                    await self.r.zadd(key, mapping)
                            
                            
                            user_messages.clear()
                            
                            try:
                                await itx.edit_original_response(content=f"⏳ Zpracováno: {msg_count} zpráv...")
                            except discord.HTTPException:
                                
                                print(f"Progress: {msg_count} messages")
                                
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"Error in {channel.name}: {e}")
        
        
        for uid, messages in user_messages.items():
            key = f"events:msg:{gid}:{uid}"
            mapping = {}
            for ts, length, is_reply in messages:
                event_data = json.dumps({"len": length, "reply": is_reply})
                mapping[event_data] = ts
            
            if mapping:
                await self.r.zadd(key, mapping)

        
        audit_ops = 0
        user_actions = defaultdict(list)  
        
        try:
            async for entry in itx.guild.audit_logs(limit=None, after=limit_date):
                if entry.user and not entry.user.bot:
                    action_type = None
                    
                    if entry.action == discord.AuditLogAction.ban:
                        action_type = "ban"
                    elif entry.action == discord.AuditLogAction.kick:
                        action_type = "kick"
                    elif entry.action == discord.AuditLogAction.unban:
                        action_type = "unban"
                    elif entry.action == discord.AuditLogAction.message_delete:
                        action_type = "msg_delete"
                    elif entry.action == discord.AuditLogAction.member_role_update:
                        action_type = "role_update"
                    elif entry.action == discord.AuditLogAction.member_update:
                        if hasattr(entry.after, "timed_out_until") and entry.after.timed_out_until:
                            action_type = "timeout"
                    
                    if action_type:
                        ts = entry.created_at.timestamp()
                        user_actions[entry.user.id].append((ts, action_type))
                        audit_ops += 1
                        
                        if isinstance(entry.user, discord.Member):
                            await self._update_user_info(entry.user)
        except Exception as e:
            print(f"Audit error: {e}")
        
        
        for uid, actions in user_actions.items():
            key = f"events:action:{gid}:{uid}"
            mapping = {}
            for ts, action_type in actions:
                event_data = json.dumps({"type": action_type})
                mapping[event_data] = ts
            
            if mapping:
                await self.r.zadd(key, mapping)

        
        verifs = 0
        VERIFICATION_LOG_CHANNEL_ID = 1404416148077809705
        log_ch = itx.guild.get_channel(VERIFICATION_LOG_CHANNEL_ID)
        
        if log_ch:
            re_approve = re.compile(r"Schválil <@!?(\d+)>")
            re_bypass = re.compile(r"Manuální bypass - <@!?(\d+)>")
            
            verification_events = defaultdict(list)  
            
            try:
                async for msg in log_ch.history(limit=None, after=limit_date):
                    if msg.author.id == self.bot.user.id:
                        uid = None
                        m = re_approve.search(msg.content)
                        if m:
                            uid = int(m.group(1))
                        else:
                            m = re_bypass.search(msg.content)
                            if m:
                                uid = int(m.group(1))
                        
                        if uid:
                            ts = msg.created_at.timestamp()
                            verification_events[uid].append(ts)
                            verifs += 1
            except:
                pass
            
            
            for uid, timestamps in verification_events.items():
                key = f"events:action:{gid}:{uid}"
                mapping = {}
                for ts in timestamps:
                    event_data = json.dumps({"type": "verification"})
                    mapping[event_data] = ts
                
                if mapping:
                    await self.r.zadd(key, mapping)

        try:
            await itx.followup.send(f"✅ **Hotovo!**\n"
                                    f"Zpracováno: {msg_count} zpráv, {audit_ops} audit akcí, {verifs} verifikací.\n"
                                    f"Data uložena do event systému.\n"
                                    f"Zkus: `/activity stats after:01-01-2025`.")
        except discord.HTTPException:
            
            print(f"Backfill completed: {msg_count} msgs, {audit_ops} actions, {verifs} verifs")

    @act_group.command(name="report", description="Zobrazí report aktivity týmu (7 a 30 dní).")
    @app_commands.checks.has_permissions(administrator=True) 
    async def report(self, itx: discord.Interaction):
        await itx.response.defer()
        gid = itx.guild.id
        today = date.today()
        
        
        d_week = today - timedelta(days=7)
        d_month = today - timedelta(days=30)
        
        
        
        
        scores_week = defaultdict(float)
        scores_month = defaultdict(float)
        
        
        pattern = f"activity:day:*:{gid}:*:*"
        async for key in self.r.scan_iter(pattern):
            parts = key.split(":")
            if len(parts) != 6: continue
            
            day_str = parts[2]
            uid = int(parts[4])
            metric = parts[5]
            
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d").date()
            except: continue
            
            val = float(await self.r.get(key) or 0)
            
            w = 1.0
            if metric in ACTION_WEIGHTS: w = ACTION_WEIGHTS[metric]
            elif metric == "messages": w = 0
            
            weighted_val = val * w
            
            
            if d >= d_week:
                scores_week[uid] += weighted_val
            
            
            if d >= d_month:
                scores_month[uid] += weighted_val

        
        top_week = sorted(scores_week.items(), key=lambda x: x[1], reverse=True)
        top_month = sorted(scores_month.items(), key=lambda x: x[1], reverse=True)
        
        
        def fmt_list(data_list):
            lines = []
            for i, (uid, sec) in enumerate(data_list, 1):
                
                
                lines.append(f"**{i}.** <@{uid}> — `{self.fmt_time(sec)}`")
            return "\n".join(lines) if lines else "Žádná data."

        
        
        limit = 25
        
        desc_week = fmt_list(top_week[:limit])
        desc_month = fmt_list(top_month[:limit])
        
        e = discord.Embed(title="📊 Report Aktivity Týmu", color=discord.Color.purple())
        e.add_field(name="📅 Posledních 7 dní", value=desc_week, inline=True)
        e.add_field(name="📅 Posledních 30 dní", value=desc_month, inline=True)
        e.set_footer(text=f"Zobrazeno TOP {limit}. Vygenerováno: {today}")
        
        await itx.followup.send(embed=e)

async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityMonitor(bot))
