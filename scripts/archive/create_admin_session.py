import secrets
import string
import hashlib
import os
import subprocess
import time

def generate_token():
    alphabet = string.ascii_letters + string.digits
    token_body = ''.join(secrets.choice(alphabet) for _ in range(36))
    return f"flx_{token_body}"

def get_token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).digest()

def main():
    token = generate_token()
    token_hash = get_token_hash(token)
    token_hash_hex = "0x" + token_hash.hex()
    
    user_id = 1474006153980551168 # Marcipan
    
    print(f"Generated Token: {token}")
    print(f"Token Hash Hex: {token_hash_hex}")
    
    # Use proper CQL syntax and values for a valid 'desktop' session
    cql = f"INSERT INTO fluxer.auth_sessions (session_id_hash, user_id, created_at, approx_last_used_at, client_ip, client_user_agent, version, client_is_desktop) VALUES ({token_hash_hex}, {user_id}, toTimestamp(now()), toTimestamp(now()), '127.0.0.1', 'MigrationScript/1.0', 1, true);"
    print(f"CQL: {cql}")
    
    # Execute via docker
    cmd = ["docker", "exec", "fluxer-cassandra-1", "cqlsh", "-e", cql]
    print("Executing CQL...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("Success! Session created.")
        # Save token to file
        with open("migration_token.txt", "w") as f:
            f.write(token)
    else:
        print("Error creating session:")
        print(result.stderr)

if __name__ == "__main__":
    main()
