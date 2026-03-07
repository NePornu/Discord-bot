import asyncio
import sys
import time
sys.path.append('/root/discord-bot')
from web.backend.generator_utils import generate_local_scenario
import json

async def test():
    print("Testing local AI scenario generation with 11k+ context dataset...")
    print("This may take a significant amount of time as the local model processes the large community knowledge base.")
    start_time = time.time()
    
    scenario = await generate_local_scenario("discourse")
    
    elapsed = time.time() - start_time
    print(f"\nGeneration completed in {elapsed:.2f} seconds.")
    print("\nResult:")
    print(json.dumps(scenario, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(test())
