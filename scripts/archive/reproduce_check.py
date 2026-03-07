import os
import requests
import redis
import json
import time
import socket
import ssl
from datetime import datetime

URLS = [
    ("Darci", "https://darci.nepornu.cz", None),
    ("Forum", "https://forum.nepornu.cz", None),
    ("Dashboard", "https://nepornu.cz/login", "html"),
    ("Druhykrok", "https://druhykrok.cz", "html"),
    ("NePornu Web", "https://nepornu.cz", "NePornu")
]

def check_ssl(hostname, port=443):
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                not_after = cert['notAfter']
                expiry_date = datetime.strptime(not_after, r'%b %d %H:%M:%S %Y %Z')
                days_left = (expiry_date - datetime.utcnow()).days
                return True, days_left
    except Exception as e:
        return False, str(e)

print("\nChecking URLs and Latency...")
for name, url, keyword in URLS:
    print(f"Checking {name} ({url})...")
    try:
        start = time.time()
        response = requests.get(url, timeout=10)
        latency = (time.time() - start) * 1000
        
        print(f"  Status: {response.status_code}")
        print(f"  Latency: {int(latency)}ms")
        if keyword:
            print(f"  Keyword '{keyword}': {'OK' if keyword in response.text else 'MISSING'}")
            
        # SSL Check
        if url.startswith("https://"):
            hostname = url.split("//")[1].split("/")[0]
            if ":" in hostname: hostname, _ = hostname.split(":")
            ok, days = check_ssl(hostname)
            print(f"  SSL: {'OK' if ok else 'FAIL'} ({days} days)")
            
    except Exception as e:
        print(f"  Error: {e}")
