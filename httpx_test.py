import asyncio
import httpx
import os

async def main():
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    print(f"Connecting to {host}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(host)
            print("HTTPX Success:", r.text)
    except Exception as e:
        print("HTTPX Failed:", repr(e))

if __name__ == "__main__":
    asyncio.run(main())
