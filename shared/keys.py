

from datetime import datetime

def day_key(dt: datetime) -> str:
    """Format datetime to YYYYMMDD string for Redis keys."""
    return dt.strftime("%Y%m%d")

def K_DAU(gid: int, d: str) -> str:
    """Daily Active Users HLL key."""
    return f"hll:dau:{gid}:{d}"

def K_HOURLY(gid: int, d: str) -> str:
    """Hourly message counts hash key."""
    return f"stats:hourly:{gid}:{d}"

def K_MSGLEN(gid: int) -> str:
    """Message length distribution hash key."""
    return f"stats:msglen:{gid}"

def K_HEATMAP(gid: int) -> str:
    """Activity heatmap (weekday x hour) hash key."""
    return f"stats:heatmap:{gid}"

def K_TOTAL_MSGS(gid: int) -> str:
    """Cumulative message count key."""
    return f"stats:total_msgs:{gid}"

def K_BACKFILL_PROGRESS(gid: int) -> str:
    """Backfill progress status key."""
    return f"backfill:progress:{gid}"

def K_LOGCHAN(gid: int) -> str:
    """Log channel setting key."""
    return f"cfg:logchan:{gid}"

def K_USER_INFO(uid: int) -> str:
    """Cached user info hash key."""
    return f"user:info:{uid}"

def K_EVENTS_MSG(gid: int, uid: int) -> str:
    """User message events sorted set key."""
    return f"events:msg:{gid}:{uid}"

def K_EVENTS_VOICE(gid: int, uid: int) -> str:
    """User voice events sorted set key."""
    return f"events:voice:{gid}:{uid}"

def K_EVENTS_ACTION(gid: int, uid: int) -> str:
    """User mod action events sorted set key."""
    return f"events:action:{gid}:{uid}"
