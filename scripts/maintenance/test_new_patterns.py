import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

# Mock common imports or use them if possible
# Since we are in the same repo, we can try to import them
import sys
import os
sys.path.append(os.path.abspath("/root/discord-bot/services/worker/commands"))
sys.path.append(os.path.abspath("/root/discord-bot"))

from patterns.detectors import PatternDetectors
from patterns.common import K_MSG, K_KW, K_EDIT, K_JOIN, K_DIARY, K_QUESTION, K_STAFF_RESPONSE

class MockRedis:
    def __init__(self):
        self.data = {}
        self.zdata = {}

    async def hgetall(self, key):
        return self.data.get(key, {})

    async def get(self, key):
        return self.data.get(key)

    async def hincrby(self, key, field, amount):
        if key not in self.data: self.data[key] = {}
        curr = int(self.data[key].get(field, 0))
        self.data[key][field] = str(curr + amount)

    async def hget(self, key, field):
        return self.data.get(key, {}).get(field)

    async def incrby(self, key, amount):
        if key not in self.data: self.data[key] = "0"
        curr = int(self.data.get(key, 0))
        self.data[key] = str(curr + amount)

    async def zscore(self, key, member):
        return self.zdata.get(key, {}).get(member)

    async def zadd(self, key, mapping):
        if key not in self.zdata: self.zdata[key] = {}
        self.zdata[key].update(mapping)

    async def lrange(self, key, start, stop):
        return self.data.get(key, [])

    async def scan(self, cursor="0", match="*", count=10):
        # Very simplified scan
        import fnmatch
        keys = [k for k in self.data.keys() if fnmatch.fnmatch(k, match)]
        return "0", keys

async def test_detectors():
    r = MockRedis()
    gid = 123
    uid = 456
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    
    detectors = PatternDetectors(gid)
    
    print("--- Testing 'Hluboké zpovědi' ---")
    # Word count > 800 and analytical style
    msg_key = K_MSG(gid, uid, today)
    r.data[msg_key] = {"word_count": "900", "msg_count": "1"}
    r.data[K_KW(gid, uid, today, "analytical_hits")] = "2"
    
    alerts = await detectors.scan_user(r, gid, uid, datetime.now(timezone.utc), today)
    found = False
    for a in alerts:
        if a.pattern_name == "Hluboké zpovědi":
            print(f"✅ Found: {a.pattern_name} - {a.description}")
            found = True
    if not found: print("❌ Pattern 'Hluboké zpovědi' not found")

    print("\n--- Testing 'Stud po dumpingu' ---")
    r.data[f"pat:del_long:{gid}:{uid}:{today}"] = "1"
    alerts = await detectors.scan_user(r, gid, uid, datetime.now(timezone.utc), today)
    found = False
    for a in alerts:
        if a.pattern_name == "Stud po dumpingu":
            print(f"✅ Found: {a.pattern_name} - {a.description}")
            found = True
    if not found: print("❌ Pattern 'Stud po dumpingu' not found")

    print("\n--- Testing 'Autoritativní přijetí' ---")
    r.data[K_STAFF_RESPONSE(gid, uid)] = "600" # 10 minutes
    alerts = await detectors.scan_user(r, gid, uid, datetime.now(timezone.utc), today)
    found = False
    for a in alerts:
        if a.pattern_name == "Autoritativní přijetí":
            print(f"✅ Found: {a.pattern_name} - {a.description}")
            found = True
    if not found: print("❌ Pattern 'Autoritativní přijetí' not found")

    print("\n--- Testing 'Pasivní pozorovatel' ---")
    uid_lurker = 789
    r.data[K_JOIN(gid, uid_lurker)] = str(int(time.time()) - 40 * 86400) # 40 days ago
    # No messages in 30d
    alerts = await detectors.scan_user(r, gid, uid_lurker, datetime.now(timezone.utc), today)
    found = False
    for a in alerts:
        if a.pattern_name == "Pasivní pozorovatel":
            print(f"✅ Found: {a.pattern_name} - {a.description}")
            found = True
    if not found: print("❌ Pattern 'Pasivní pozorovatel' not found")

    print("\n--- Testing 'Moderátorský syndrom' ---")
    uid_preachy = 111
    r.data[K_MSG(gid, uid_preachy, today)] = {"msg_count": "10", "reply_count": "1"}
    r.data[K_KW(gid, uid_preachy, today, "preachy")] = "5"
    alerts = await detectors.scan_user(r, gid, uid_preachy, datetime.now(timezone.utc), today)
    found = False
    for a in alerts:
        if a.pattern_name == "Moderátorský syndrom":
            print(f"✅ Found: {a.pattern_name} - {a.description}")
            found = True
    if not found: print("❌ Pattern 'Moderátorský syndrom' not found")

if __name__ == "__main__":
    asyncio.run(test_detectors())
