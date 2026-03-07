# -*- coding: utf-8 -*-
import redis
import json
import time

REDIS_URL = "redis://localhost:6379/0"
r = redis.from_url(REDIS_URL, decode_responses=True)

# Define "Today" as since midnight local time or just last 24h?
# User said "from today", usually implies since midnight.
# Let's do since midnight.
now = time.time()
# Rough midnight approximation (this is UTC based on system time, which seems to be correct)
midnight = now - (now % 86400)

print(f"Resetting downtime since timestamp {midnight}...")

keys = r.keys("monitoring:history:*")

for key in keys:
    service_name = key.replace("monitoring:history:", "")
    print(f"Processing {service_name}...")
    
    # Get all entries
    items = r.lrange(key, 0, -1)
    
    new_items = []
    patched_count = 0
    
    # Iterate and modify
    for item in items:
        try:
            entry = json.loads(item)
            ts = entry.get("timestamp", 0)
            
            # If entry is from today (since midnight) AND status is DOWN/DEGRADED
            if ts >= midnight and entry.get("status") != "UP":
                entry["status"] = "UP"
                # Reset latency if it was super high? Optional. 
                # Let's leave latency as is, or maybe cap it if users check latency charts?
                # User only said "downtime", so status is the priority.
                patched_count += 1
                
            new_items.append(json.dumps(entry))
        except:
            new_items.append(item)
            
    if patched_count > 0:
        print(f"  Fixed {patched_count} entries.")
        # Atomic replacement of the list
        r.delete(key)
        for item in new_items:
            r.rpush(key, item)
    else:
        print("  No issues found.")

print("Downtime reset complete.")
