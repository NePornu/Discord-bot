import redis
import re

r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)

user_msg_counts = {}
user_channels = {}

# Pattern: stats:channel:615171377783242769:CHANNEL_ID:DATE
print("Scanning for all channel stats keys...")
cursor = '0'
all_keys = []
while cursor != 0:
    cursor, keys = r.scan(cursor=cursor, match="stats:channel:615171377783242769:*:*", count=5000)
    all_keys.extend(keys)

print(f"Found {len(all_keys)} channel stat keys.")

for key in all_keys:
    parts = key.split(':')
    if len(parts) >= 5:
        channel_id = parts[3]
        try:
            data = r.hgetall(key)
            for uid, count_str in data.items():
                if uid in ['total', 'unique']: continue
                
                count = int(count_str)
                user_msg_counts[uid] = user_msg_counts.get(uid, 0) + count
                
                if uid not in user_channels:
                    user_channels[uid] = set()
                user_channels[uid].add(channel_id)
        except Exception as e:
            pass

print("\n--- Top 15 Discord Users by Volume ---")
sorted_users = sorted(user_msg_counts.items(), key=lambda x: x[1], reverse=True)[:15]

for uid, count in sorted_users:
    user_info = r.hgetall(f"user:info:{uid}")
    name = user_info.get("name", uid) if user_info else uid
    if name.endswith("#0"): name = name[:-2]
    # Filter out bots if obvious
    if name != "Nepornu_bot":
        print(f"{name} ({uid}): {count} messages")

print("\n--- Top 15 Discord Users by Channel Roaming ---")
sorted_roamers = sorted(user_channels.items(), key=lambda x: len(x[1]), reverse=True)[:15]
for uid, channels in sorted_roamers:
    user_info = r.hgetall(f"user:info:{uid}")
    name = user_info.get("name", uid) if user_info else uid
    if name.endswith("#0"): name = name[:-2]
    if name != "Nepornu_bot":
        print(f"{name} ({uid}): {len(channels)} unique channels")
