import redis
from datetime import datetime, timedelta

r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)

# 1. Gather daily activity per user
# user_daily_activity[uid][date_str] = count
user_daily_activity = {}

print("Scanning user daily stats keys...")
cursor = '0'
all_keys = []
while cursor != 0:
    cursor, keys = r.scan(cursor=cursor, match="stats:user_daily:615171377783242769:*", count=5000)
    all_keys.extend(keys)

for key in all_keys:
    parts = key.split(':')
    if len(parts) >= 4:
        date_str = parts[3]
        try:
            # It's a zset
            data = r.zrange(key, 0, -1, withscores=True)
            for uid, score in data:
                count = int(score)
                if uid not in user_daily_activity:
                    user_daily_activity[uid] = {}
                user_daily_activity[uid][date_str] = count
        except Exception as e:
            pass

# 2. Identify churned users
all_dates = set()
for uid, dates in user_daily_activity.items():
    all_dates.update(dates.keys())

if not all_dates:
    print("No data found.")
    exit()

max_date_str = max(all_dates)
max_dt = datetime.strptime(max_date_str, "%Y%m%d")
# We'll consider them churned if they haven't posted in the last 7 days of the dataset
cutoff_dt = max_dt - timedelta(days=7)
cutoff_str = cutoff_dt.strftime("%Y%m%d")

churned_users = []
active_users = []

for uid, dates in user_daily_activity.items():
    if len(dates) < 5:
        continue # Not enough data
    
    last_active_date_str = max(dates.keys())
    
    if last_active_date_str < cutoff_str:
        churned_users.append((uid, last_active_date_str))
    else:
        active_users.append(uid)

print(f"Total Users with 5+ active days: {len(churned_users) + len(active_users)}")
print(f"Active Users (active in last 7 days): {len(active_users)}")
print(f"Churned Users (no activity in last 7 days): {len(churned_users)}")

# 3. Analyze trajectory of churned users
abrupt_drops = 0
gradual_fades = 0

for uid, last_active in churned_users:
    last_dt = datetime.strptime(last_active, "%Y%m%d")
    
    daily_totals = []
    for i in range(14, -1, -1):
        dt = last_dt - timedelta(days=i)
        d_str = dt.strftime("%Y%m%d")
        total_msgs = user_daily_activity[uid].get(d_str, 0)
        daily_totals.append(total_msgs)
    
    last_3_days = sum(daily_totals[-3:])
    prev_3_days = sum(daily_totals[-6:-3])
    
    if last_3_days >= prev_3_days and last_3_days > 0:
        abrupt_drops += 1
    elif last_3_days < prev_3_days and prev_3_days > 0:
        gradual_fades += 1

print("\n--- Churn Trajectories ---")
print(f"Abrupt Drops (Active until the last minute then vanished): {abrupt_drops}")
print(f"Gradual Fades (Slowly stopped talking over days/weeks): {gradual_fades}")

# Print a few examples of users who churned abruptly to see if we can find them in DB
print("\nExamples of Abrupt Drops User IDs:")
count = 0
for uid, last_active in churned_users:
    last_dt = datetime.strptime(last_active, "%Y%m%d")
    daily_totals = []
    for i in range(14, -1, -1):
        dt = last_dt - timedelta(days=i)
        d_str = dt.strftime("%Y%m%d")
        total_msgs = user_daily_activity[uid].get(d_str, 0)
        daily_totals.append(total_msgs)
    
    last_3_days = sum(daily_totals[-3:])
    prev_3_days = sum(daily_totals[-6:-3])
    
    if last_3_days >= prev_3_days and last_3_days > 0:
        user_info = r.hgetall(f"user:info:{uid}")
        name = user_info.get("name", uid) if user_info else uid
        print(f"User {name} ({uid}): Last active {last_active}")
        count += 1
        if count >= 10: break

