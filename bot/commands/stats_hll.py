# activity_hll_optimized.py — ultra-lean DAU/WAU/MAU Cog + heavy-hitters (top users/channels)
# - žádné ENV; config níže
# - Redis HLL pro DAU/WAU/MAU (~12kB/den/guild)
# - 1 async worker (batch+dedupe), cooldown per user
# - Space-Saving heavy hitters (RAM only) pro dnešek (UTC) → !topusers / !topchannels
# - heartbeat log + incidenty
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional, List, Iterable
from collections import Counter, defaultdict, deque

import discord
from discord.ext import commands, tasks
import redis.asyncio as redis

# ----------------- CONFIG -----------------
CONFIG = {
    "REDIS_URL": "redis://redis-hll:6379/0",
    "RETENTION_DAYS": 40,
    "USER_COOLDOWN_SEC": 60,
    "VOICE_MIN_MINUTES": 5,
    "QUEUE_MAXSIZE": 50000,
    "BATCH_MAX": 500,
    "BATCH_MAX_WAIT_MS": 50,
    "LOG_INTERVAL_SEC": 60,
    "VERBOSE_LOG": True,       # heartbeat vypíše top 2 kanály/uživatele (bez IO)
    "INCIDENT_COOLDOWN_S": 300,
    "TOP_K": 32,               # velikost heavy-hitter okna (čím větší, tím přesnější; RAM ~ O(TOP_K))
}

# ----------------- Keys -----------------
def day_key(dt: datetime) -> str: return dt.strftime("%Y%m%d")
def K_DAU(gid: int, d: str) -> str: return f"hll:dau:{gid}:{d}"
def K_LOGCHAN(gid: int) -> str: return f"hll:cfg:logchan:{gid}"

# Dashboard stats keys
def K_HOURLY(gid: int, d: str) -> str: return f"stats:hourly:{gid}:{d}"
def K_MSGLEN(gid: int) -> str: return f"stats:msglen:{gid}"
def K_HEATMAP(gid: int) -> str: return f"stats:heatmap:{gid}"
def K_TOTAL_MSGS(gid: int) -> str: return f"stats:total_msgs:{gid}"

# ----------------- Helpers -----------------
class TTLSet:
    __slots__ = ("_exp",)
    def __init__(self): self._exp: Dict[Tuple[int,int,str], float] = {}
    def allow(self, key: Tuple[int,int,str], ttl_s: int, now: Optional[float] = None) -> bool:
        t = now or asyncio.get_event_loop().time()
        e = self._exp.get(key, 0.0)
        if t < e: return False
        self._exp[key] = t + ttl_s
        return True
    def sweep(self):
        t = asyncio.get_event_loop().time()
        stale = [k for k,v in self._exp.items() if v <= t]
        for k in stale: self._exp.pop(k, None)

# Space-Saving heavy hitters (approx top-k) — O(k) paměť, O(1) update
class SpaceSaving:
    __slots__ = ("k","c","err")
    def __init__(self, k: int = 32):
        self.k = k
        self.c: Dict[int,int] = {}     # id -> count
        self.err: Dict[int,int] = {}   # id -> max možná chyba
    def update(self, key: int, w: int = 1):
        if key in self.c:
            self.c[key] += w
            return
        if len(self.c) < self.k:
            self.c[key] = w
            self.err[key] = 0
            return
        # najdi min
        mkey = min(self.c, key=self.c.get)
        mval = self.c[mkey]
        # nahrad nejmenší
        self.err.pop(mkey, None)
        self.c.pop(mkey, None)
        self.c[key] = mval + w
        self.err[key] = mval
    def top(self, n: int) -> List[Tuple[int,int]]:
        return sorted(self.c.items(), key=lambda kv: kv[1], reverse=True)[:max(1,n)]
    def clear(self):
        self.c.clear(); self.err.clear()

# ----------------- Cog -----------------
class ActivityHLLOptCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.r: redis.Redis = redis.from_url(CONFIG["REDIS_URL"], decode_responses=True)

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=CONFIG["QUEUE_MAXSIZE"])
        self.cooldowns = TTLSet()
        self._voice_start: Dict[Tuple[int,int], datetime] = {}

        # interval metriky (heartbeat)
        self.interval_msgs_by_channel: Dict[int, Counter] = defaultdict(Counter)
        self.interval_msgs_by_user: Dict[int, Counter]    = defaultdict(Counter)
        self.interval_interactions: Dict[int, int] = defaultdict(int)
        self.interval_voice_hits: Dict[int, int]   = defaultdict(int)

        # heavy hitters per guild (dnešek UTC)
        self._hh_day = day_key(datetime.now(timezone.utc))
        self.hh_users: Dict[int, SpaceSaving]   = defaultdict(lambda: SpaceSaving(CONFIG["TOP_K"]))
        self.hh_chans: Dict[int, SpaceSaving]   = defaultdict(lambda: SpaceSaving(CONFIG["TOP_K"]))

        # stats/log
        self.stats = {"enqueued": 0, "written": 0, "drop_cooldown": 0, "drop_queue": 0}
        self.last_flush = asyncio.get_event_loop().time()
        self._incidents: Dict[int, deque] = defaultdict(lambda: deque(maxlen=5))
        self._errors_recent: Dict[int, deque] = defaultdict(lambda: deque(maxlen=3))

        # tasks
        self.worker_task = self.bot.loop.create_task(self._worker())
        self.log_task.start()
        self.housekeep_local.start()
        self.roll_day_task.start()

    async def _collect_dashboard_stats(self, m: discord.Message):
        """Collect message statistics for dashboard visualization."""
        try:
            # DEDUPLICATION: Check if this message has already been processed by another bot instance
            # We use a short-lived lock in Redis based on the Message ID
            lock_key = f"lock:msg:{m.id}"
            if not await self.r.set(lock_key, "1", ex=10, nx=True):
                # Lock exists, skip processing (other bot instance got it)
                return

            now = datetime.now(timezone.utc)
            today = day_key(now)
            hour = now.hour
            weekday = now.weekday()  # 0=Monday, 6=Sunday
            gid = m.guild.id
            cid = m.channel.id
            uid = m.author.id
            msg_len = len(m.content)
            
            # Use pipeline for atomic Redis operations
            pipe = self.r.pipeline()
            
            # 1. Hourly message count
            pipe.hincrby(K_HOURLY(gid, today), hour, 1)
            pipe.expire(K_HOURLY(gid, today), 60 * 86400)  # 60 days TTL
            
            # 2. Message length distribution (using sorted set)
            # Bucket message lengths into ranges for histogram
            if msg_len == 0:
                bucket = 0
            elif msg_len <= 10:
                bucket = 5  # represents 0-10 range
            elif msg_len <= 50:
                bucket = 30  # represents 11-50 range
            elif msg_len <= 100:
                bucket = 75  # represents 51-100 range
            elif msg_len <= 200:
                bucket = 150  # represents 101-200 range
            else:
                bucket = 250  # represents 200+ range
            
            pipe.zincrby(K_MSGLEN(gid), 1, bucket)
            
            # 3. Heatmap (weekday_hour format, e.g., "0_14" = Monday 2pm)
            heatmap_key = f"{weekday}_{hour}"
            pipe.hincrby(K_HEATMAP(gid), heatmap_key, 1)
            pipe.expire(K_HEATMAP(gid), 60 * 86400)  # 60 days TTL
            
            # 4. Cumulative total messages
            pipe.incr(K_TOTAL_MSGS(gid))
            
            # 5. NEW: Per-channel statistics
            # Track daily messages per channel
            channel_key = f"stats:channel:{gid}:{cid}:{today}"
            pipe.incr(channel_key)
            pipe.expire(channel_key, 60 * 86400)
            
            # Track total messages per channel (all-time)
            channel_total_key = f"stats:channel_total:{gid}"
            pipe.zincrby(channel_total_key, 1, f"{cid}")
            
            # 6. NEW: User leaderboards
            # Total messages per user (for leaderboard)
            leaderboard_key = f"leaderboard:messages:{gid}"
            pipe.zincrby(leaderboard_key, 1, f"{uid}")
            
            # Daily messages per user (for filtered leaderboard)
            user_daily_key = f"stats:user_daily:{gid}:{today}"
            pipe.zincrby(user_daily_key, 1, f"{uid}")
            pipe.expire(user_daily_key, 60 * 86400) # 60 days TTL
            
            # Average message length per user (for quality score)
            user_len_key = f"leaderboard:msg_lengths:{gid}:{uid}"
            pipe.lpush(user_len_key, msg_len)
            pipe.ltrim(user_len_key, 0, 99)  # Keep last 100 messages
            pipe.expire(user_len_key, 30 * 86400)
            
            # 7. NEW: Channel activity by hour (for channel peak analysis)
            channel_hourly_key = f"stats:channel_hourly:{gid}:{cid}"
            pipe.hincrby(channel_hourly_key, hour, 1)
            pipe.expire(channel_hourly_key, 60 * 86400)
            
            # Execute pipeline
            await pipe.execute()
        except Exception as e:
            # Don't let stats collection errors crash the bot
            print(f"Dashboard stats collection error: {e}")

    # --------------- Lifecycle ---------------
    def cog_unload(self):
        for t in (self.worker_task, self.log_task, self.housekeep_local, self.roll_day_task):
            try: t.cancel()
            except Exception: pass

    # --------------- Internal ---------------
    async def _enqueue(self, gid: int, uid: int, ts: Optional[datetime] = None):
        ts = ts or datetime.now(timezone.utc)
        d = day_key(ts)
        if not self.cooldowns.allow((gid, uid, d), CONFIG["USER_COOLDOWN_SEC"]):
            self.stats["drop_cooldown"] += 1
            return
        try:
            self.queue.put_nowait((gid, uid, d))
            self.stats["enqueued"] += 1
        except asyncio.QueueFull:
            self.stats["drop_queue"] += 1

    async def _worker(self):
        while not self.bot.is_closed():
            try: item = await self.queue.get()
            except Exception: break
            batch = [item]
            start = asyncio.get_event_loop().time()
            while len(batch) < CONFIG["BATCH_MAX"] and \
                  (asyncio.get_event_loop().time() - start)*1000 < CONFIG["BATCH_MAX_WAIT_MS"]:
                try: batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty: await asyncio.sleep(0); break
            uniq: List[Tuple[int,int,str]] = list(set(batch))
            try:
                pipe = self.r.pipeline()
                ttl = CONFIG["RETENTION_DAYS"] * 86400
                for gid, uid, d in uniq:
                    k = K_DAU(gid, d)
                    pipe.pfadd(k, str(uid))
                    pipe.expire(k, ttl, nx=True)
                await pipe.execute()
                self.stats["written"] += len(uniq)
            except Exception as e:
                # zaznamenej chybu pro poslední guild v batchi (ok pro log)
                gid = uniq[-1][0] if uniq else 0
                self._errors_recent[gid].append(str(e))
            finally:
                for _ in batch: self.queue.task_done()

    # --------------- Events ---------------
    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild: return
        await self._enqueue(m.guild.id, m.author.id)
        # heartbeat counters
        if CONFIG["VERBOSE_LOG"]:
            self.interval_msgs_by_channel[m.guild.id][m.channel.id] += 1
            self.interval_msgs_by_user[m.guild.id][m.author.id] += 1
        # heavy hitters (dnešek)
        if day_key(datetime.now(timezone.utc)) != self._hh_day:
            self._roll_day_reset()
        self.hh_users[m.guild.id].update(m.author.id, 1)
        self.hh_chans[m.guild.id].update(m.channel.id, 1)
        
        # Dashboard stats collection
        await self._collect_dashboard_stats(m)

    @commands.Cog.listener()
    async def on_interaction(self, inter: discord.Interaction):
        if inter.user and inter.guild:
            await self._enqueue(inter.guild.id, inter.user.id)
            if CONFIG["VERBOSE_LOG"]:
                self.interval_interactions[inter.guild.id] += 1
            # počítej interakce do heavy hitters uživatelů (váha 1)
            if day_key(datetime.now(timezone.utc)) != self._hh_day:
                self._roll_day_reset()
            self.hh_users[inter.guild.id].update(inter.user.id, 1)

    @commands.Cog.listener()
    async def on_voice_state_update(self, m: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if m.bot: return
        now = datetime.now(timezone.utc)
        key = (m.guild.id, m.id)
        joined = (before.channel is None and after.channel is not None)
        left   = (before.channel is not None and after.channel is None)
        moved  = (before.channel and after.channel and before.channel.id != after.channel.id)
        if joined or moved: self._voice_start[key] = now
        if left or moved:
            start = self._voice_start.pop(key, None)
            if start and (now - start) >= timedelta(minutes=CONFIG["VOICE_MIN_MINUTES"]):
                await self._enqueue(m.guild.id, m.id)
                # voice účast započti do heavy hitters uživatelů (váha 1)
                if day_key(datetime.now(timezone.utc)) != self._hh_day:
                    self._roll_day_reset()
                self.hh_users[m.guild.id].update(m.id, 1)

    # --------------- Rolling unions ---------------
    async def _rolling_uniques(self, gid: int, days: int) -> int:
        now = datetime.now(timezone.utc)
        keys = [K_DAU(gid, day_key(now - timedelta(days=i))) for i in range(days)]
        existing = [k for k in keys if await self.r.exists(k)]
        if not existing: return 0
        tmp = f"_tmp:hll:{gid}:{day_key(now)}:{days}"
        await self.r.pfmerge(tmp, *existing)
        await self.r.expire(tmp, 30)
        return await self.r.pfcount(tmp)

    # --------------- Day roll (UTC midnight) ---------------
    def _roll_day_reset(self):
        self._hh_day = day_key(datetime.now(timezone.utc))
        for ss in (self.hh_users, self.hh_chans):
            for gid in list(ss.keys()):
                ss[gid].clear()

    @tasks.loop(minutes=1)
    async def roll_day_task(self):
        # když překročíme půlnoc UTC, resetni heavy-hitter okna
        if day_key(datetime.now(timezone.utc)) != self._hh_day:
            self._roll_day_reset()

    @roll_day_task.before_loop
    async def _before_roll(self): await self.bot.wait_until_ready()

    # --------------- Housekeeping ---------------
    @tasks.loop(minutes=5)
    async def housekeep_local(self): self.cooldowns.sweep()
    @housekeep_local.before_loop
    async def _before_hk(self): await self.bot.wait_until_ready()

    # --------------- Heartbeat ---------------
    @tasks.loop(seconds=CONFIG["LOG_INTERVAL_SEC"])
    async def log_task(self):
        now = datetime.now(timezone.utc)
        today = day_key(now)
        for guild in self.bot.guilds:
            chan_id = await self.r.get(K_LOGCHAN(guild.id))
            if not chan_id: continue
            chan = guild.get_channel(int(chan_id))
            if not chan: continue
            dau = await self.r.pfcount(K_DAU(guild.id, today))
            emb = discord.Embed(title="📊 Analytics", color=0x5865F2, timestamp=now)
            emb.add_field(name="DAU (dnes)", value=str(dau))
            emb.add_field(name="Queue", value=f"{self.queue.qsize()}/{CONFIG['QUEUE_MAXSIZE']}")
            emb.add_field(name="Enq/Written", value=f"{self.stats['enqueued']}/{self.stats['written']}")
            emb.add_field(name="Drops (cd/q)", value=f"{self.stats['drop_cooldown']}/{self.stats['drop_queue']}")
            # poslední chyby (max 5)
            if self._errors_recent[guild.id]:
                emb.add_field(name="Chyby", value="\n".join(self._errors_recent[guild.id]), inline=False)
            # verbose: top 2 kanály/uživatelé v intervalu (ne heavy-hitters)
            if CONFIG["VERBOSE_LOG"]:
                top_ch = self.interval_msgs_by_channel[guild.id].most_common(2)
                top_us = self.interval_msgs_by_user[guild.id].most_common(2)
                txt_ch = ", ".join(f"<#{cid}>×{c}" for cid,c in top_ch) or "—"
                txt_us = ", ".join(f"<@{uid}>×{c}" for uid,c in top_us) or "—"
                emb.add_field(name="Interval top kanály", value=txt_ch, inline=False)
                emb.add_field(name="Interval top uživ.", value=txt_us, inline=False)
            try: await chan.send(embed=emb)
            except Exception as e:
                self._errors_recent[guild.id].append(f"send: {e}")
        # reset intervalu
        if CONFIG["VERBOSE_LOG"]:
            self.interval_msgs_by_channel.clear()
            self.interval_msgs_by_user.clear()
            self.interval_interactions.clear()
            self.interval_voice_hits.clear()

    @log_task.before_loop
    async def _before_log(self): await self.bot.wait_until_ready()

    # --------------- Commands (prefix) ---------------
    @commands.command(name="dau", help="DAU pro den (0=today, 1=yesterday, ...)")
    @commands.has_guild_permissions(manage_guild=True)
    async def cmd_dau(self, ctx: commands.Context, days_ago: int = 0):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        n = await self.r.pfcount(K_DAU(ctx.guild.id, day_key(dt)))
        await ctx.reply(f"DAU {dt.strftime('%Y-%m-%d')}: **{n}**", mention_author=False)

    @commands.command(name="wau", help="WAU (7d rolling)")
    @commands.has_guild_permissions(manage_guild=True)
    async def cmd_wau(self, ctx: commands.Context):
        n = await self._rolling_uniques(ctx.guild.id, 7)
        await ctx.reply(f"WAU (7d rolling): **{n}**", mention_author=False)

    @commands.command(name="mau", help="MAU (30d rolling) nebo zadej N (<= retenční okno)")
    @commands.has_guild_permissions(manage_guild=True)
    async def cmd_mau(self, ctx: commands.Context, window_days: int = 30):
        window_days = max(1, min(window_days, CONFIG["RETENTION_DAYS"]))
        n = await self._rolling_uniques(ctx.guild.id, window_days)
        await ctx.reply(f"Rolling {window_days}d uniques: **{n}**", mention_author=False)

    @commands.command(name="anloghere", help="Nastaví aktuální kanál pro heartbeat logy")
    @commands.has_guild_permissions(manage_guild=True)
    async def cmd_loghere(self, ctx: commands.Context):
        await self.r.set(K_LOGCHAN(ctx.guild.id), str(ctx.channel.id))
        await ctx.reply("✅ Tento kanál nastaven jako logovací.", mention_author=False)

    @commands.command(name="topusers", help="Top N uživatelé dnes (approx heavy hitters, RAM only)")
    @commands.has_guild_permissions(manage_guild=True)
    async def cmd_topusers(self, ctx: commands.Context, n: int = 10):
        ss = self.hh_users[ctx.guild.id]
        pairs = ss.top(n)
        if not pairs:
            return await ctx.reply("— žádná data dnes —", mention_author=False)
        lines = [f"{i+1}. <@{uid}> — **{cnt}**" for i,(uid,cnt) in enumerate(pairs)]
        await ctx.reply("**Top uživatelé (dnes, approx):**\n" + "\n".join(lines), mention_author=False)

    @commands.command(name="topchannels", help="Top N kanály dnes (approx heavy hitters, RAM only)")
    @commands.has_guild_permissions(manage_guild=True)
    async def cmd_topchannels(self, ctx: commands.Context, n: int = 10):
        ss = self.hh_chans[ctx.guild.id]
        pairs = ss.top(n)
        if not pairs:
            return await ctx.reply("— žádná data dnes —", mention_author=False)
        lines = [f"{i+1}. <#{cid}> — **{cnt}**" for i,(cid,cnt) in enumerate(pairs)]
        await ctx.reply("**Top kanály (dnes, approx):**\n" + "\n".join(lines), mention_author=False)

    # --------------- Member Growth Tracking (Redis) ---------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        month_key = datetime.now().strftime("%Y-%m")
        # stats:joins:{gid}, field=YYYY-MM
        await self.r.hincrby(f"stats:joins:{member.guild.id}", month_key, 1)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot: return
        try:
            month_key = datetime.now().strftime("%Y-%m")
            # stats:leaves:{gid}, field=YYYY-MM
            await self.r.hincrby(f"stats:leaves:{member.guild.id}", month_key, 1)
        except Exception as e:
            # Handle case where connection is closed or other error
            print(f"[ActivityHLL] Error in on_member_remove: {e}")

async def setup(bot: commands.Bot):
    # varování na intent
    if not bot.intents.message_content:
        print("[activity_hll] WARNING: message_content intent disabled (text activity neuvidím).")
    if not bot.intents.voice_states:
        print("[activity_hll] WARNING: voice_states intent disabled (voice neuvidím).")
    await bot.add_cog(ActivityHLLOptCog(bot))

