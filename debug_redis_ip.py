
import redis
import sys

try:
    print("Connecting to 172.22.0.2...")
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    keys = r.keys("presence:*")
    print(f"Found {len(keys)} presence keys.")
    for key in keys:
        val = r.get(key)
        ttl = r.ttl(key)
        print(f"Key: {key}, Value: {val}, TTL: {ttl}")
        
    print("Presence totals:")
    total_keys = r.keys("presence:total:*")
    for key in total_keys:
        print(f"{key}: {r.get(key)}")

except Exception as e:
    print(f"Error: {e}")
