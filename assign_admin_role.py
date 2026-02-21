import time
import subprocess
import os

def generate_snowflake():
    # Simple snowflake generation
    timestamp = int(time.time() * 1000) - 1420070400000
    if timestamp < 0: timestamp = 0
    return (timestamp << 22) + 1

def main():
    guild_id = 1474016949225660417
    user_id = 1474006153980551168
    role_id = generate_snowflake()
    
    print(f"Generated Role ID: {role_id}")
    
    # Permission 8 is ADMINISTRATOR
    cql_create_role = f"INSERT INTO fluxer.guild_roles (guild_id, role_id, name, permissions, position, color, hoist, mentionable, version) VALUES ({guild_id}, {role_id}, 'MigrationAdmin', 8, 999, 0, false, false, 1);"
    
    # Add role to member
    cql_assign_role = f"UPDATE fluxer.guild_members SET role_ids = role_ids + {{{role_id}}} WHERE guild_id = {guild_id} AND user_id = {user_id};"
    
    print("Creating Role...")
    cmd1 = ["docker", "exec", "fluxer-cassandra-1", "cqlsh", "-e", cql_create_role]
    subprocess.run(cmd1, check=True)
    
    print("Assigning Role...")
    cmd2 = ["docker", "exec", "fluxer-cassandra-1", "cqlsh", "-e", cql_assign_role]
    subprocess.run(cmd2, check=True)
    
    print("Success! Admin role assigned.")

if __name__ == "__main__":
    main()
