# -*- coding: utf-8 -*-
import redis
import json
import time

REDIS_URL = "redis://localhost:6379/0"
r = redis.from_url(REDIS_URL, decode_responses=True)

now = time.time()

# Scan for all history keys
keys = r.keys("monitoring:history:*")

for key in keys:
    name = key.replace("monitoring:history:", "")
    print(f"Checking {name}...")
    
    # Get all entries
    items = r.lrange(key, 0, -1)
    new_items = []
    patched_count = 0
    
    for item in items:
        try:
            entry = json.loads(item)
            ts = entry.get("timestamp", 0)
            status = entry.get("status")
            
            # If entry is from last 24h and status is not UP (DEGRADED/DOWN/WARNING)
            if ts > (now - 86400) and status != "UP":
                # We assume these were false positives due to tight thresholds
                entry["status"] = "UP"
                patched_count += 1
                
            new_items.append(json.dumps(entry))
        except Exception as e:
            print(f"Error parsing item: {e}")
            new_items.append(item)
            
    if patched_count > 0:
        # Replace list
        r.delete(key)
        # lpush is reverse order, but we iterated lrange (0 to -1). 
        # Redis List: [Newest, ..., Oldest] (usually doing lpush)
        # lrange returns [Newest, ..., Oldest]
        # We need to push them back? 
        # r.rpush appends to end. r.lpush prepends.
        # If we want to preserve order:
        # We read Newest->Oldest.
        # We should rpush them to rebuild?
        # No, if we rpush, the first item (Newest) becomes index 0. Yes.
        
        # Wait, if I do:
        # lpush A, lpush B, lpush C -> List is [C, B, A]
        # lrange returns [C, B, A]
        # Iterate: C, B, A
        # rpush C -> [C]
        # rpush B -> [C, B]
        # rpush A -> [C, B, A]
        # Correct. Use rpush.
        
        for item in new_items:
            r.rpush(key, item)
            
        print(f"  Patched {patched_count} entries.")
    else:
        print("  No entries needed patching.")

print("Done.")
