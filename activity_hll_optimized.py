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
                                                                                                 [ Read 328 lines ]
^G Get Help      ^O Write Out     ^W Where Is      ^K Cut Text      ^J Justify       ^C Cur Pos       M-U Undo         M-A Mark Text    M-] To Bracket   M-Q Previous     ^B Back          ^◀ Prev Word
^X Exit          ^R Read File     ^\ Replace       ^U Uncut Text    ^T To Spell      ^_ Go To Line    M-E Redo         M-6 Copy Text    ^Q Where Was     M-W Next         ^F Forward       ^▶ Next Word
