# -*- coding: utf-8 -*-
"""
Service Monitor - Monitors services and sends Discord alerts.
Uses Redis for persistent state to prevent spam on restarts.
"""
import os
import time
import requests
import redis
import logging
import json
import socket
import ssl
from datetime import datetime

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHANNEL_ID = os.getenv("ALERT_CHANNEL_ID")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHECK_INTERVAL = 60  # Seconds
STRIKE_LIMIT = 5  # Require 5 consecutive failures before DOWN
RECOVERY_LIMIT = 3  # Require 3 consecutive successes before UP recovery
ALERT_COOLDOWN = 1800  # 30 minutes between alerts for same service (prevents spam)

# Service Configuration
SERVICES = [
    {
        "name": "Darci - darci.nepornu.cz",
        "type": "http",
        "url": "https://darci.nepornu.cz",
        "external_url": "https://darci.nepornu.cz",
        "initial_uptime": 97.8825,
        "latency_threshold": 15000, 
        "timeout": 30
    },
    {
        "name": "Druhykrok.cz",
        "type": "http",
        "url": "https://druhykrok.cz",
        "external_url": "https://druhykrok.cz",
        "initial_uptime": 99.6628,
        "keyword": "html" 
    },
    {
        "name": "E-maily - nepornu.cz",
        "type": "tcp",
        "host": "smtp.gmail.com",
        "port": 587,
        "external_url": "https://nepornu.cz",
        "initial_uptime": 99.9804
    },
    {
        "name": "Fórum Nepornu - forum.nepornu.cz",
        "type": "http",
        "url": "https://forum.nepornu.cz",
        "external_url": "https://forum.nepornu.cz",
        "initial_uptime": 99.4248,
        "latency_threshold": 5000,
        "timeout": 30
    },
    {
        "name": "NePornu Web - nepornu.cz",
        "type": "http",
        "url": "https://nepornu.cz", 
        "external_url": "https://nepornu.cz",
        "initial_uptime": 99.2948,
        "keyword": "NePornu"
    },
    {
        "name": "Discord Bot",
        "type": "redis_heartbeat",
        "key": "bot:heartbeat",
        "timeout": 120,
        "initial_uptime": 99.99
    },
    {
        "name": "Dashboard",
        "type": "http",
        "url": "https://nepornu.cz/login",
        "external_url": "https://nepornu.cz/login",
        "initial_uptime": 99.95,
        "keyword": "html",
        "latency_threshold": 5000,
        "timeout": 30
    }
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_redis_client():
    return redis.from_url(REDIS_URL, decode_responses=True)

def get_service_state(r, name):
    """Get service state from Redis."""
    key = f"monitor:state:{name}"
    data = r.get(key)
    if data:
        return json.loads(data)
    return None

def set_service_state(r, name, state):
    """Save service state to Redis."""
    key = f"monitor:state:{name}"
    r.set(key, json.dumps(state))

def get_last_alert_time(r, name):
    """Get last alert time from Redis (persistent across restarts)."""
    key = f"monitor:last_alert:{name}"
    val = r.get(key)
    return float(val) if val else 0

def set_last_alert_time(r, name, ts):
    """Set last alert time in Redis."""
    key = f"monitor:last_alert:{name}"
    r.set(key, str(ts))
    r.expire(key, 86400)  # Expire after 24h

def update_redis_status(r, service_states):
    """Writes the current status of all services to Redis for the dashboard."""
    try:
        status_data = {
            "last_updated": time.time(),
            "next_update": time.time() + CHECK_INTERVAL,
            "services": []
        }
        
        for svc in SERVICES:
            name = svc["name"]
            state = service_states.get(name, {})
            
            # Calculate uptime
            total = state.get("total_checks", 1)
            up = state.get("up_checks", 1)
            uptime_pct = (up / total) * 100 if total > 0 else 100.0
            
            # Store history
            history_entry = {
                "timestamp": int(time.time()),
                "latency_ms": state.get("last_latency", 0),
                "status": state.get("status", "UNKNOWN")
            }
            
            history_key = f"monitoring:history:{name}"
            r.lpush(history_key, json.dumps(history_entry))
            r.ltrim(history_key, 0, 1439)  # Keep last 24h

            status_data["services"].append({
                "name": name,
                "status": state.get("status", "UNKNOWN"),
                "url": svc.get("external_url", ""),
                "latency_ms": state.get("last_latency", 0),
                "uptime_pct": round(uptime_pct, 4),
                "type": svc.get("type", "http"),
                "ssl_days": state.get("ssl_days", None)
            })
            
        r.set("monitoring:status", json.dumps(status_data))
    except Exception as e:
        logging.error(f"Failed to update Redis status: {e}")

def send_alert(r, service_name, status, error_details=None):
    """Send alert to Discord with Redis-persistent cooldown."""
    if not BOT_TOKEN or not ALERT_CHANNEL_ID:
        logging.warning("No BOT_TOKEN or ALERT_CHANNEL_ID configured, skipping alert.")
        return False
    
    # Check cooldown from Redis (persists across restarts)
    last_alert = get_last_alert_time(r, service_name)
    elapsed = time.time() - last_alert
    
    if elapsed < ALERT_COOLDOWN:
        remaining = int(ALERT_COOLDOWN - elapsed)
        logging.info(f"Skipping alert for {service_name} - cooldown active ({remaining}s remaining)")
        return False
    
    # Update last alert time BEFORE sending to prevent race conditions
    set_last_alert_time(r, service_name, time.time())

    color = 0x00FF00 if status == "UP" else 0xFF0000
    emoji = "✅" if status == "UP" else "🔴"
    title = f"{emoji} {service_name} is {status}"
    
    embed = {
        "title": title,
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
        "fields": []
    }
    
    if error_details and status == "DOWN":
        error_msg = str(error_details)[:200]
        embed["fields"].append({"name": "Error", "value": error_msg, "inline": False})
    
    embed["footer"] = {"text": f"Next alert possible in {ALERT_COOLDOWN // 60} minutes"}

    url = f"https://discord.com/api/v10/channels/{ALERT_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"embeds": [embed]}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            logging.info(f"Sent {status} alert for {service_name}")
            return True
        else:
            logging.error(f"Failed to send alert: {response.status_code} {response.text}")
            return False
    except Exception as e:
        logging.error(f"Error sending alert: {e}")
        return False

def check_http(url, keyword=None, timeout=10):
    try:
        start = time.time()
        response = requests.get(url, timeout=timeout, allow_redirects=True, 
                              headers={"User-Agent": "StatusMonitor/1.0"})
        latency = (time.time() - start) * 1000
        
        if response.status_code >= 400:
             return False, f"Status: {response.status_code}", int(latency)

        if keyword and keyword.lower() not in response.text.lower():
             return False, f"Keyword '{keyword}' missing", int(latency)
             
        return True, "OK", int(latency)
    except requests.exceptions.Timeout:
        return False, "Connection timeout", 0
    except requests.exceptions.ConnectionError:
        return False, "Connection failed", 0
    except Exception as e:
        return False, str(e)[:100], 0

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

def check_redis_heartbeat(key, timeout):
    try:
        start = time.time()
        r = get_redis_client()
        last_heartbeat = r.get(key)
        r.close()
        latency = (time.time() - start) * 1000
        
        if not last_heartbeat:
            return False, "No heartbeat found", int(latency)
            
        last_time = float(last_heartbeat)
        if time.time() - last_time > timeout:
            return False, f"Heartbeat stale ({int(time.time() - last_time)}s ago)", int(latency)
            
        return True, "OK", int(latency)
    except Exception as e:
        return False, f"Redis error: {e}", 0

def check_tcp(host, port):
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex((host, port))
        sock.close()
        latency = (time.time() - start) * 1000
        
        if result == 0:
            return True, "OK", int(latency)
        else:
            return False, f"Connection failed (Code: {result})", int(latency)
    except Exception as e:
        return False, str(e), 0

def monitor_loop():
    logging.info("Starting monitoring loop...")
    logging.info(f"Alert cooldown: {ALERT_COOLDOWN}s, Strike limit: {STRIKE_LIMIT}, Recovery limit: {RECOVERY_LIMIT}")
    
    r = get_redis_client()
    service_states = {}
    
    # Initialize states - try to load from Redis first
    logging.info("Loading saved service states from Redis...")
    for service in SERVICES:
        name = service["name"]
        try:
            saved_state = get_service_state(r, name)
            
            if saved_state:
                service_states[name] = saved_state
                status = saved_state.get('status', 'UNKNOWN')
                strikes = saved_state.get('strikes', 0)
                logging.info(f"✓ Loaded state for '{name}': {status} (strikes: {strikes})")
            else:
                logging.info(f"✗ No saved state for '{name}', initializing fresh")
                initial_pct = service.get("initial_uptime", 100.0)
                total_checks = 1000000 
                up_checks = int(total_checks * (initial_pct / 100))
                
                service_states[name] = {
                    "status": "UP", 
                    "strikes": 0,
                    "recovery_strikes": 0,
                    "total_checks": total_checks,
                    "up_checks": up_checks,
                    "last_latency": 0
                }
        except Exception as e:
            logging.error(f"Error loading state for {name}: {e}")
            service_states[name] = {
                "status": "UP", 
                "strikes": 0,
                "recovery_strikes": 0,
                "total_checks": 1000000,
                "up_checks": 1000000,
                "last_latency": 0
            }
    
    logging.info(f"State loading complete. {len(service_states)} services initialized.")

    while True:
        try:
            for service in SERVICES:
                name = service["name"]
                is_up = False
                details = ""
                latency = 0

                current_state = service_states[name]
                
                if service["type"] == "http":
                    timeout = service.get("timeout", 10)
                    is_up, details, latency = check_http(service["url"], service.get("keyword"), timeout)
                    
                    # SSL Check
                    if is_up and service["url"].startswith("https://"):
                        try:
                            hostname = service["url"].split("//")[1].split("/")[0]
                            port = 443
                            if ":" in hostname:
                                hostname, port = hostname.split(":")
                                port = int(port)
                                
                            has_ssl, days_left = check_ssl(hostname, port)
                            if has_ssl:
                                current_state["ssl_days"] = days_left
                        except Exception as e:
                            logging.error(f"SSL Check error for {name}: {e}")

                elif service["type"] == "redis_heartbeat":
                    is_up, details, latency = check_redis_heartbeat(service["key"], service["timeout"])
                elif service["type"] == "tcp":
                    is_up, details, latency = check_tcp(service["host"], service["port"])
                
                # Update stats
                current_state["last_latency"] = latency
                current_state["total_checks"] += 1
                if is_up:
                    current_state["up_checks"] += 1
                
                prev_status = current_state["status"]
                
                if is_up:
                    current_state["strikes"] = 0
                    
                    if prev_status == "DOWN":
                        current_state["recovery_strikes"] += 1
                        logging.info(f"{name} recovery {current_state['recovery_strikes']}/{RECOVERY_LIMIT}")
                        
                        if current_state["recovery_strikes"] >= RECOVERY_LIMIT:
                            logging.info(f"{name} recovered!")
                            current_state["status"] = "UP"
                            current_state["recovery_strikes"] = 0
                            send_alert(r, name, "UP")
                    else:
                        current_state["recovery_strikes"] = 0
                        current_state["status"] = "UP"
                else:
                    current_state["recovery_strikes"] = 0
                    
                    if prev_status in ["UP", "WARNING", "DEGRADED"]:
                        current_state["strikes"] += 1
                        logging.info(f"{name} strike {current_state['strikes']}/{STRIKE_LIMIT}")
                        
                        if current_state["strikes"] >= STRIKE_LIMIT:
                            logging.error(f"{name} is DOWN!")
                            current_state["status"] = "DOWN"
                            send_alert(r, name, "DOWN", details)
                
                # Save state to Redis
                set_service_state(r, name, current_state)
            
            # Update dashboard status
            update_redis_status(r, service_states)
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logging.error(f"Error in monitor loop: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor_loop()
