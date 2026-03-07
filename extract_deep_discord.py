import redis
import json

r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
gid = "615171377783242769"

print("--- 1. Activity Heatmap (When is Discord most active?) ---")
heatmap_key = f"stats:heatmap:{gid}"
heatmap = r.hgetall(heatmap_key)
if heatmap:
    # weekday_hour: count
    hours_activity = {h: 0 for h in range(24)}
    days_activity = {d: 0 for d in range(7)}
    for k, v in heatmap.items():
        day, hour = map(int, k.split('_'))
        hours_activity[hour] += int(v)
        days_activity[day] += int(v)
    
    print("Most Active Hours (Top 5):")
    sorted_hours = sorted(hours_activity.items(), key=lambda x: x[1], reverse=True)[:5]
    for h, c in sorted_hours:
        print(f"{h}:00 - {h}:59 -> {c} interactions")
        
    print("\nMost Active Days of Week (0=Mon, 6=Sun):")
    sorted_days = sorted(days_activity.items(), key=lambda x: x[1], reverse=True)
    for d, c in sorted_days:
        print(f"Day {d} -> {c} interactions")
else:
    print("No heatmap data found.")

print("\n--- 2. Join/Leave Trends ---")
joins = r.hgetall(f"stats:joins:{gid}")
leaves = r.hgetall(f"stats:leaves:{gid}")
print(f"Joins recorded: {joins}")
print(f"Leaves recorded: {leaves}")

print("\n--- 3. DAU Counts (HyperLogLog) ---")
# Find all recent DAU keys
cursor = '0'
dau_keys = []
while cursor != 0:
    cursor, keys = r.scan(cursor=cursor, match=f"hll:dau:{gid}:*", count=1000)
    dau_keys.extend(keys)

if dau_keys:
    dau_counts = {}
    for key in dau_keys:
        date_str = key.split(':')[-1]
        count = r.pfcount(key)
        dau_counts[date_str] = count
    
    print("Recent Daily Active Users:")
    for d_str in sorted(dau_counts.keys(), reverse=True)[:7]:
        print(f"{d_str}: {dau_counts[d_str]} unique users")
else:
    print("No DAU data found.")

print("\n--- 4. Message Length Distribution (All time) ---")
msglen_data = r.zrange(f"stats:msglen:{gid}", 0, -1, withscores=True)
if msglen_data:
    for bucket, count in msglen_data:
        print(f"Length <= {bucket} chars: {count} messages")
else:
    print("No message length data found.")
