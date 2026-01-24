import asyncio
from web.backend.main import app
from httpx import AsyncClient

async def check_endpoint():
    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            # We need to simulate authentication if required
            # The endpoint uses _=Depends(require_auth)
            # We can try to mock the session or just see if it hits the auth barrier or crashes.
            
            # Actually, let's just create a dummy request object context if possible, 
            # or better: bypass auth for testing or invoke the function directly.
            
            # Invoking function directly is hard due to Dependency injection.
            # Let's try to mock the session in the client.
            
            # Simulating a session with a user_id
            # NOTE: Starlette TestClient with SessionMiddleware is tricky. 
            # Simpler approach: Inspect the function directly in utils.py/main.py?
            
            pass 
            
    except Exception as e:
        print(e)

# Simpler: Just run a script that imports the logic used by the endpoint.
# The endpoint calls `utils.get_security_score`.
from web.backend.utils import get_security_score, get_redis

async def run_logic():
    try:
        # Guild ID hardcoded for typical user or passed
        # I'll check what guild_id the user is likely using.
        # From context, maybe 615171377783242769
        guild_id = 615171377783242769
        print(f"Testing calculation for guild {guild_id}")
        score = await get_security_score(guild_id)
        print("Score result:", score)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_logic())
