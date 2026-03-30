from __future__ import annotations
import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from shared.python.config import config

logger = logging.getLogger("PatternDetector")

@dataclass
class PatternAlert:
    pattern_name: str
    user_id: int
    risk_level: str  # "critical", "warning", "info"
    description: str
    recommended_action: str
    emoji: str = "🔍"

    @property
    def color(self) -> int:
        return {"critical": 0xFF0000, "warning": 0xFFA500, "info": 0x3498DB}[self.risk_level]

    @property
    def level_label(self) -> str:
        return {"critical": "🔴 KRITICKÉ", "warning": "🟡 VAROVÁNÍ", "info": "🟢 INFO"}[self.risk_level]

# ─── Redis Helper Keys ───────────────────────────────────────────────
def K_KW(gid, uid, date, group):  return f"pat:kw:{gid}:{uid}:{date}:{group}"
def K_MSG(gid, uid, date):        return f"pat:msg:{gid}:{uid}:{date}"
def K_DEL(gid, uid, date):        return f"pat:del:{gid}:{uid}:{date}"
def K_EDIT(gid, uid, date):       return f"pat:edit:{gid}:{uid}:{date}"
def K_DIARY(gid, uid):            return f"pat:diary_unanswered:{gid}:{uid}"
def K_REPLY(gid, a, b):           return f"pat:reply_pair:{gid}:{min(a,b)}:{max(a,b)}"
def K_FIRST(gid, uid):            return f"pat:first_msg:{gid}:{uid}"
def K_MUTE(gid, uid):            return f"pat:mute:{gid}:{uid}"
def K_ALERT(gid, uid, pat):       return f"pat:alert_sent:{gid}:{uid}:{pat}"
def K_JOIN(gid, uid):             return f"pat:user_join:{gid}:{uid}"
def K_LAST_SCAN(gid):             return f"pat:last_scan:{gid}"
def K_QUESTION(gid, uid, mid):    return f"pat:question:{gid}:{uid}:{mid}"
def K_STAFF_RESPONSE(gid, uid):  return f"pat:staff_resp:{gid}:{uid}"
def K_MSG_LEN(gid, mid):         return f"pat:msg_len:{gid}:{mid}"
def K_NOTES(gid, uid):           return f"pat:notes:{gid}:{uid}"
def K_THREAD(gid, uid):          return f"pat:thread:{gid}:{uid}"
def K_THREAD_UID(tid):           return f"pat:thread_uid:{tid}"
def K_STATUS(gid, uid):          return f"pat:status:{gid}:{uid}"
def K_FOLLOWUP(gid, uid):        return f"pat:followup:{gid}:{uid}"
def K_LAST_ACTIVITY(gid, uid):   return f"pat:last_act:{gid}:{uid}"

PAT_TTL = 730 * 86400  # 2 years

def is_staff(member) -> bool:
    """Check if a member is a staff/worker (Admin, Mod, Mentor, etc.)."""
    if member.guild_permissions.administrator:
        return True
    
    staff_keywords = {
        "mentor", "moderátor", "admin", "průvodce", "tým", "koordinátor", 
        "pracovník", "vedení", "kouč", "lektor", "expert", "specialista", "správce"
    }
    return any(
        any(kw in role.name.lower() for kw in staff_keywords)
        for role in member.roles
    )

def is_diary_channel(channel) -> bool:
    """Check if a channel is a diary channel by name."""
    name = channel.name.lower()
    return any(dn in name for dn in config.DIARY_CHANNEL_NAMES)

def get_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")
