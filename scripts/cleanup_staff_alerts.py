import redis
import os

r = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
staff_ids = ["933255920786477077", "1177153580998856717", "471218810964410368"]

print("--- Data exclusion from Redis ---")
for uid in staff_ids:
    # 1. Alerts
    cursor = "0"
    while True:
        cursor, keys = r.scan(cursor=cursor, match=f"pat:alert_sent:*:{uid}:*", count=500)
        for k in keys:
            print(f"Deleting alert: {k}")
            r.delete(k)
        if cursor == "0" or cursor == 0:
            break
            
    # 2. Daily patterns
    cursor = "0"
    while True:
        cursor, keys = r.scan(cursor=cursor, match=f"pat:kw:*:{uid}:*", count=500)
        for k in keys:
            # print(f"Deleting kw: {k}")
            r.delete(k)
        if cursor == "0" or cursor == 0:
            break

    # 3. Message stats
    cursor = "0"
    while True:
        cursor, keys = r.scan(cursor=cursor, match=f"pat:msg:*:{uid}:*", count=500)
        for k in keys:
            # print(f"Deleting msg: {k}")
            r.delete(k)
        if cursor == "0" or cursor == 0:
            break

print("Cleanup done.")
