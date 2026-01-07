
import redis
import sys

try:
    r = redis.from_url("redis://redis-hll:6379/0", decode_responses=True)
    keys = r.keys("presence:*")
    print(f"Found {len(keys)} presence keys.")
    for key in keys:
        val = r.get(key)
        ttl = r.ttl(key)
        print(f"Key: {key}, Value: {val}, TTL: {ttl}")
    
    # Also check live logs
    logs_len = r.llen("dashboard:live_logs")
    print(f"Live logs count: {logs_len}")
    if logs_len > 0:
        print(f"Last log: {r.lindex('dashboard:live_logs', -1)}")

except Exception as e:
    print(f"Error: {e}")
