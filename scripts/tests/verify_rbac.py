
import asyncio
import sys
# sys.path.append('/root/discord-bot') # already in path potentially, but good to ensure
from web.backend.utils import add_dashboard_user, get_dashboard_permissions, get_dashboard_team, remove_dashboard_user

async def verify_rbac():
    GUILD_ID = 615171377783242769 # NePornu
    TEST_USER_ID = "999999999"
    TEST_USER_DATA = {"username": "TestUser", "avatar": ""}
    TEST_PERMS = ["view_stats", "export_data"]
    
    print("--- Starting RBAC Verification ---")
    
    # 1. Add User
    print(f"1. Adding user {TEST_USER_ID} with perms {TEST_PERMS}...")
    success = await add_dashboard_user(GUILD_ID, TEST_USER_ID, TEST_USER_DATA, TEST_PERMS)
    if success: print("✅ User added successfully.")
    else: print("❌ Failed to add user.")
    
    # 2. Check Permissions
    print("2. Checking permissions...")
    perms = await get_dashboard_permissions(GUILD_ID, TEST_USER_ID, "guest")
    print(f"   Got permissions: {perms}")
    if set(perms) == set(TEST_PERMS): print("✅ Permissions match.")
    else: print(f"❌ Permissions mismatch. Expected {TEST_PERMS}")
    
    # 3. Check Team List
    print("3. Fetching team list...")
    team = await get_dashboard_team(GUILD_ID)
    found = False
    for member in team:
        if member["id"] == TEST_USER_ID:
            found = True
            print(f"   Found member: {member}")
            break
    if found: print("✅ User found in team list.")
    else: print("❌ User NOT found in team list.")
    
    # 4. Remove User
    print("4. Removing user...")
    success = await remove_dashboard_user(GUILD_ID, TEST_USER_ID)
    if success: print("✅ User removed.")
    else: print("❌ Failed to remove user.")
    
    # 5. Verify Removal
    perms_after = await get_dashboard_permissions(GUILD_ID, TEST_USER_ID, "guest")
    if not perms_after: print("✅ User has no permissions after removal.")
    else: print(f"❌ User still has permissions: {perms_after}")
    
    print("--- Verification Complete ---")

if __name__ == "__main__":
    asyncio.run(verify_rbac())
