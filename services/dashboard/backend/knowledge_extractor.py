import json
import subprocess
import os
import asyncio
from shared.redis_client import get_redis

async def extract_discourse_knowledge(limit=200):
    """Extract a large batch of forum posts for training data."""
    print(f"Extracting {limit} forum posts...")
    cmd = [
        "docker", "exec", "app", "sudo", "-u", "postgres", "psql", "-d", "discourse",
        "-t", "-c", f"SELECT raw FROM posts WHERE post_type=1 AND length(raw) > 50 ORDER BY created_at DESC LIMIT {limit};"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        posts = [p.strip() for p in result.stdout.split('\n') if p.strip()]
        return posts
    except Exception as e:
        print(f"Error extracting Discourse knowledge: {e}")
        return []

async def extract_discord_knowledge(limit=500):
    """Extract a large batch of recent Discord interactions for training data."""
    print(f"Extracting {limit} Discord messages...")
    r = await get_redis()
    knowledge = []
    try:
        # 1. Try Automod historical logs (high density of "scenarios")
        keys = await r.keys("automod:pending:*")
        for key in keys[:limit//2]:
            data = await r.get(key)
            if data:
                msg = json.loads(data)
                content = msg.get("content", "").strip()
                if content:
                    knowledge.append(f"Automod Trigger: {content}")
        
        # 2. Extract real moderator training responses (gold data)
        training_keys = await r.keys("training:results:*")
        for key in training_keys[:limit//2]:
            entries = await r.lrange(key, 0, -1)
            for entry in entries:
                try:
                    data = json.loads(entry)
                    reply = data.get("user_reply", "").strip()
                    score = data.get("evaluation", {}).get("score", "?")
                    if reply:
                        knowledge.append(f"Moderator Reply ({score}/10): {reply}")
                except:
                    pass
        
        return knowledge
    except Exception as e:
        print(f"Error extracting Discord knowledge: {e}")
        return []

async def main():
    # Pull a massive dataset for deeper contextual understanding
    discourse_data = await extract_discourse_knowledge(2000)
    discord_data = await extract_discord_knowledge(500)
    
    knowledge_base = {
        "forum_posts": discourse_data,
        "discord_events": discord_data
    }
    
    output_path = "/root/discord-bot/data/community_knowledge.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(knowledge_base, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Knowledge extraction complete. Saved to {output_path}")
    print(f"Total Forum entries: {len(discourse_data)}")
    print(f"Total Discord entries: {len(discord_data)}")

if __name__ == "__main__":
    asyncio.run(main())
