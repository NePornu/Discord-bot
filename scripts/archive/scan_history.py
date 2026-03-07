import redis
import json

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
KEY = "monitoring:history:Darci - darci.nepornu.cz"

items = r.lrange(KEY, 0, -1)
print(f"Total items: {len(items)}")
count = 0
for i, item in enumerate(items):
    data = json.loads(item)
    if data.get("status") != "UP":
        print(f"Index {i}: {data}")
        count += 1
        if count > 5: break

if count == 0:
    print("All items are UP.")
