import asyncio
import os
import sys
import logging

# Ensure absolute paths for imports
sys.path.append('/app')
from shared.keycloak_client import keycloak_client
from shared.redis_client import get_redis_client

# Explicit mapping for testing
GROUP_MAPPING = {
    "/Dobrovolníci/E-koučové": "E-kouč",
    "/Dobrovolníci/Moderátoři Discord": "Moderátor",
    "/Pracovníci NP/Koordinátoři": "Koordinátor NP"
}

async def test_mapping(discord_id):
    r = await get_redis_client()
    
    # 1. Check link
    kc_user_id = await r.get(f"sso:keycloak_link:{discord_id}")
    print(f"--- SSO Test for Discord ID: {discord_id} ---")
    
    if not kc_user_id:
        print("❌ Discord link not found in Redis (sso:keycloak_link:ID)")
        # List some keys for debugging
        keys = []
        async for key in r.scan_iter("sso:keycloak_link:*"):
            keys.append(key)
        if keys:
            print(f"Sample linked Discord IDs in Redis: {[k.split(':')[-1] for k in keys[:5]]}")
        return

    print(f"✅ Found Keycloak User ID: {kc_user_id}")

    # 2. Fetch groups
    groups = await keycloak_client.get_user_groups(kc_user_id)
    if not isinstance(groups, list):
        print(f"❌ Failed to fetch groups: {groups}")
        return

    group_paths = [g.get("path") for g in groups]
    print(f"✅ Groups found in Keycloak: {group_paths}")

    # 3. Apply mapping
    assigned = []
    for path, role_name in GROUP_MAPPING.items():
        if path in group_paths:
            assigned.append(role_name)
    
    if assigned:
        print(f"⭐ User SHOULD get these roles: {assigned}")
    else:
        print("ℹ️ User has no mapped groups, no roles would be added.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/test_kc_mapping.py <discord_id>")
    else:
        asyncio.run(test_mapping(sys.argv[1]))
