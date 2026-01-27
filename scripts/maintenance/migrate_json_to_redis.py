
import json
import asyncio
import redis.asyncio as redis
from pathlib import Path

DATA_DIR = Path("data")
JSON_PATH = DATA_DIR / "member_counts.json"
GUILD_ID = 615171377783242769

async def migrate():
    if not JSON_PATH.exists():
        print("No JSON file found to migrate.")
        return

    print("Migrating member_counts.json to Redis...")
    r = redis.from_url("redis://172.22.0.2:6379/0", decode_responses=True)
    
    try:
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        
        pipe = r.pipeline()
        count = 0
        
        for date_key, values in data.items():
            
            
            if isinstance(values, dict):
                joins = values.get("joins", 0)
                leaves = values.get("leaves", 0)
                
                
                pipe.hset(f"stats:joins:{GUILD_ID}", date_key, joins)
                pipe.hset(f"stats:leaves:{GUILD_ID}", date_key, leaves)
                
                
                
                count += 1
            else:
                
                pass
                
        await pipe.execute()
        print(f"✓ Migrated {count} months of data to Redis.")
        
        
        test_joins = await r.hgetall(f"stats:joins:{GUILD_ID}")
        print(f"Redis Verification (Joins): {len(test_joins)} entries found.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        await r.close()

if __name__ == "__main__":
    asyncio.run(migrate())
