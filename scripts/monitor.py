import asyncio
import datetime
import json
import logging
import os
import socket
import ssl
import time
import httpx
import redis.asyncio as redis
import psutil
import shutil
import docker
import subprocess
from datetime import datetime
from shared.python.ai_client import AIClient

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHANNEL_ID = os.getenv("ALERT_CHANNEL_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "3600"))
IGNORE_PATTERNS = [p.strip() for p in os.getenv("IGNORE_PATTERNS", "fluxer,sso,modest_raman").split(",") if p.strip()]

# Services to monitor
SERVICES = [
    {"name": "Discourse HTTP", "type": "http", "url": "http://app:80"},
    {"name": "Keycloak HTTP", "type": "http", "url": "http://keycloak:8080/health"},
    {"name": "SSO Portal", "type": "http", "url": "http://sso-portal:8000"},
    {"name": "Redis", "type": "tcp", "host": "redis", "port": 6379},
    {"name": "Postgres", "type": "tcp", "host": "keycloak-db", "port": 5432}
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def get_redis_client():
    return redis.from_url(REDIS_URL, decode_responses=True)

async def get_last_alert_time(r, key):
    val = await r.get(f"monitor:alert:{key}")
    return float(val) if val else 0

async def set_last_alert_time(r, key, timestamp):
    await r.set(f"monitor:alert:{key}", str(timestamp))

async def send_alert(r, name, status, error_details=None, fields=None, diagnosis=None, force=False):
    """Send alert to Discord only if status changes or 12h cooldown passed"""
    if not BOT_TOKEN or not ALERT_CHANNEL_ID:
        return
        
    for p in IGNORE_PATTERNS:
        if p.lower() in name.lower():
            return
            
    last_status = await r.get(f"monitor:sent_status:{name}")
    last_alert = await get_last_alert_time(r, name)
    
    # Determine if we should send
    # 1. Force is True
    # 2. Status has changed (e.g. OK -> WARNING, WARNING -> OK)
    # 3. It's been more than 12 hours (long-term reminder for persistent issues)
    is_changed = status != last_status
    is_stale = time.time() - last_alert > 43200 # 12 hours
    
    if not force and not is_changed and not is_stale:
        return

    # Don't update last_alert_time if it's just a repeated state we decided to skip
    # (But here we decided to send it if it's changed or stale)
    await set_last_alert_time(r, name, time.time())
    await r.set(f"monitor:sent_status:{name}", status)

    color = 0x00FF00 if status in ["UP", "OK"] else 0xFF0000
    if status == "WARNING":
        color = 0xFFAA00
        emoji = "⚠️"
    elif status == "URGENT":
        color = 0xFF0000
        emoji = "🚨"
    else:
        emoji = "✅" if status in ["UP", "OK"] else "🔴"
        
    title = f"{emoji} {name}: {status}"
    
    embed = {
        "title": title,
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
        "fields": fields or []
    }
    
    if error_details:
        embed["fields"].append({"name": "Details", "value": str(error_details)[:400], "inline": False})
    
    if diagnosis:
        embed["fields"].append({"name": "🧠 AI Analýza", "value": diagnosis, "inline": False})
    
    embed["footer"] = {"text": "Smart AI Monitor"}

    url = f"https://discord.com/api/v10/channels/{ALERT_CHANNEL_ID}/messages"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    payload = {"embeds": [embed]}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, headers=headers, json=payload)
        logging.info(f"Alert sent for {name} ({status})")
    except Exception as e:
        logging.error(f"Error sending alert: {e}")

async def check_http(url):
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            latency = (time.time() - start) * 1000
            if 200 <= resp.status_code < 400:
                return True, "OK", int(latency)
            return False, f"Status: {resp.status_code}", int(latency)
    except Exception as e:
        return False, str(e), 0

async def check_tcp(host, port):
    try:
        start = time.time()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10.0)
        writer.close()
        await writer.wait_closed()
        latency = (time.time() - start) * 1000
        return True, "OK", int(latency)
    except Exception as e:
        return False, str(e), 0

async def check_system_health(r, states, persistence):
    # Disk
    try:
        usage = shutil.disk_usage("/")
        disk_pct = (usage.used / usage.total) * 100
        new_status = "URGENT" if disk_pct > 95 else ("WARNING" if disk_pct > 85 else "OK")
        
        if new_status != states.get("System Disk"):
            fields = [{"name": "Usage", "value": f"{disk_pct:.1f}%", "inline": True}]
            await send_alert(r, "System Disk", new_status, fields=fields, force=True)
            states["System Disk"] = new_status
            if new_status != "OK":
                subprocess.run(["docker", "system", "prune", "-f", "--filter", "until=24h"], capture_output=True)
    except Exception as e: logging.error(f"Disk check error: {e}")

    # RAM
    try:
        ram_pct = psutil.virtual_memory().percent
        old_status = states.get("System RAM", "OK")
        if ram_pct > 97: new_status = "WARNING"
        elif ram_pct < 88: new_status = "OK"
        else: new_status = old_status
            
        if new_status != old_status:
            p = persistence.setdefault("System RAM", {"status": None, "count": 0})
            if p["status"] == new_status: p["count"] += 1
            else: p["status"] = new_status; p["count"] = 1
            
            required = 3 if new_status == "WARNING" else 5
            if p["count"] >= required:
                await send_alert(r, "System RAM", new_status, fields=[{"name": "Usage", "value": f"{ram_pct}%"}])
                states["System RAM"] = new_status
                persistence.pop("System RAM", None)
        else:
            persistence.pop("System RAM", None)
    except Exception as e: logging.error(f"RAM check error: {e}")

    # CPU
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        old_status = states.get("System CPU", "OK")
        if cpu_pct > 99: new_status = "WARNING"
        elif cpu_pct < 85: new_status = "OK"
        else: new_status = old_status
            
        if new_status != old_status:
            p = persistence.setdefault("System CPU", {"status": None, "count": 0})
            if p["status"] == new_status: p["count"] += 1
            else: p["status"] = new_status; p["count"] = 1
            
            required = 3 if new_status == "WARNING" else 5
            if p["count"] >= required:
                await send_alert(r, "System CPU", new_status, fields=[{"name": "Load", "value": f"{cpu_pct}%"}])
                states["System CPU"] = new_status
                persistence.pop("System CPU", None)
        else:
            persistence.pop("System CPU", None)
    except Exception as e: logging.error(f"CPU check error: {e}")

async def check_docker(r, states, client):
    try:
        for c in client.containers.list(all=True):
            if c.name == "discord-monitor": continue
            s = c.attrs['State']
            unhealthy = 'Health' in s and s['Health']['Status'] == 'unhealthy'
            is_down = s['Status'] in ["restarting"] or (s['Status'] == "exited" and s['ExitCode'] != 0) or unhealthy
            
            curr_status = "DOWN" if is_down else "UP"
            if curr_status != states.get(f"cnt:{c.name}"):
                diagnosis = None
                if curr_status == "DOWN":
                    logs = c.logs(tail=20).decode('utf-8', errors='ignore')
                    diagnosis = await AIClient.analyze_logs(c.name, logs)
                
                details = f"Status: {s['Status']}, Exit: {s['ExitCode']}" + (" (UNHEALTHY)" if unhealthy else "")
                await send_alert(r, f"Container {c.name}", curr_status, error_details=details, diagnosis=diagnosis, force=True)
                states[f"cnt:{c.name}"] = curr_status
    except Exception as e: logging.error(f"Docker check error: {e}")

async def monitor_loop():
    logging.info("Starting Smart AI Monitor...")
    r = await get_redis_client()
    docker_client = docker.from_env()
    local_states = {}
    persistence = {}
    
    # Initialize CPU measurement
    psutil.cpu_percent(interval=None)
    
    while True:
        try:
            for key in ["System Disk", "System RAM", "System CPU"]:
                saved = await r.get(f"monitor:status:{key}")
                if saved: local_states[key] = saved
            
            for s in SERVICES:
                success, details, latency = await check_http(s["url"]) if s["type"] == "http" else await check_tcp(s["host"], s["port"])
                curr = "UP" if success else "DOWN"
                if curr != await r.get(f"monitor:status:svc:{s['name']}"):
                    diagnosis = None
                    if curr == "DOWN":
                        # Try to find matching container logs
                        svc_lower = s['name'].lower()
                        for c in docker_client.containers.list(all=True):
                            if svc_lower in c.name.lower() or c.name.lower() in svc_lower:
                                logs = c.logs(tail=20).decode('utf-8', errors='ignore')
                                diagnosis = await AIClient.analyze_logs(s['name'], logs)
                                break
                    
                    await send_alert(r, s['name'], curr, error_details=details, diagnosis=diagnosis, force=True)
                    await r.set(f"monitor:status:svc:{s['name']}", curr)

            await check_system_health(r, local_states, persistence)
            await check_docker(r, local_states, docker_client)
            
            for k, v in local_states.items(): await r.set(f"monitor:status:{k}", v)
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Loop error: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(monitor_loop())
