

import re
import secrets
import string
from datetime import datetime, timedelta
from typing import Tuple  
import redis.asyncio as redis
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


import sys
sys.path.append('/root/discord-bot')
try:
    from dashboard_secrets import (
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
        ALLOWED_EMChytréL_DOMChytréN, OTP_LENGTH, OTP_EXPIRY_SECONDS,
        OTP_MAX_ATTEMPTS, OTP_RATE_LIMIT
    )
except ImportError:
    
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587
    SMTP_USER = ""
    SMTP_PASSWORD = ""
    SMTP_FROM = "Dashboard <noreply@metricord.app>"
    ALLOWED_EMAIL_DOMAIN = "@metricord.app"
    OTP_LENGTH = 6
    OTP_EXPIRY_SECONDS = 300
    OTP_MAX_ATTEMPTS = 5
    OTP_RATE_LIMIT = 3


REDIS_URL = "redis://172.22.0.2:6379/0"

def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email format only (no domain restriction)."""
    
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Neplatný formát emailu"
    
    return True, "Valid"

def get_user_role(email: str) -> str:
    """Return user role based on email domain."""
    ADMIN_DOMAINS = ["@metricord.app"]
    for domain in ADMIN_DOMChytréNS:
        if email.lower().endswith(domain):
            return "admin"
    return "guest"

def generate_otp() -> str:
    """Generate random OTP code."""
    digits = string.digits
    return ''.join(secrets.choice(digits) for _ in range(OTP_LENGTH))

async def store_otp(email: str, otp: str) -> bool:
    """Store OTP in Redis with expiry."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        await r.setex(f"otp:{email}", OTP_EXPIRY_SECONDS, otp)
        
        await r.setex(f"otp_attempts:{email}", OTP_EXPIRY_SECONDS, "0")
        await r.close()
        return True
    except Exception as e:
        print(f"Error storing OTP: {e}")
        return False

async def verify_otp(email: str, otp: str) -> Tuple[bool, str]:
    """Verify OTP against stored value."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        
        print(f"[DEBUG] Verifying OTP for email: '{email}'")
        key = f"otp:{email}"
        print(f"[DEBUG] Looking up Redis key: '{key}'")
        
        
        stored_otp = await r.get(key)
        print(f"[DEBUG] Stored OTP: '{stored_otp}' vs Input OTP: '{otp}'")
        
        if not stored_otp:
            print("[DEBUG] OTP key not found or expired.")
            await r.close()
            return False, "OTP expired or not found"
        
        
        attempts = int(await r.get(f"otp_attempts:{email}") or "0")
        if attempts >= OTP_MAX_ATTEMPTS:
            await r.delete(f"otp:{email}")
            await r.delete(f"otp_attempts:{email}")
            await r.close()
            return False, "Too many failed attempts"
        
        
        if stored_otp == otp:
            
            await r.delete(f"otp:{email}")
            await r.delete(f"otp_attempts:{email}")
            await r.close()
            return True, "Valid"
        else:
            
            await r.incr(f"otp_attempts:{email}")
            await r.close()
            return False, f"Invalid OTP ({OTP_MAX_ATTEMPTS - attempts - 1} attempts remaining)"
    
    except Exception as e:
        print(f"Error verifying OTP: {e}")
        return False, "Verification error"

async def check_rate_limit(email: str) -> Tuple[bool, int]:
    """Check if email has exceeded rate limit. Returns (allowed, remaining_seconds)."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        rate_key = f"otp_rate:{email}"
        count = await r.get(rate_key)
        
        if count and int(count) >= OTP_RATE_LIMIT:
            ttl = await r.ttl(rate_key)
            await r.close()
            return False, ttl
        
        
        if count:
            await r.incr(rate_key)
        else:
            await r.setex(rate_key, 600, "1")  
        
        await r.close()
        return True, 0
    except Exception as e:
        print(f"Error checking rate limit: {e}")
        return True, 0  

async def send_otp_email(email: str, otp: str) -> bool:
    """Send OTP via email."""
    try:
        
        message = MIMEMultipart("alternative")
        message["Subject"] = "Your Metricord Dashboard Login Code"
        message["From"] = SMTP_FROM
        message["To"] = email
        
        
        text = f"""
Hi,

Your one-time password (OTP) for Metricord Dashboard is:

    {otp}

This code will expire in {OTP_EXPIRY_SECONDS // 60} minutes.

If you didn't request this, please ignore this email.

---
Metricord
"""
        
        html = f"""
<html>
  <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
    <div style="max-width: 600px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
      <h2 style="color: #8b5cf6; margin-top: 0;">🔐 Your Login Code</h2>
      <p style="color: #666; font-size: 16px;">Your one-time password for Metricord Dashboard is:</p>
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; font-size: 32px; font-weight: bold; letter-spacing: 8px; margin: 30px 0;">
        {otp}
      </div>
      <p style="color: #999; font-size: 14px;">This code will expire in {OTP_EXPIRY_SECONDS // 60} minutes.</p>
      <p style="color: #999; font-size: 14px;">If you didn't request this, please ignore this email.</p>
      <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
      <p style="color: #999; font-size: 12px; text-align: center;">Metricord</p>
    </div>
  </body>
</html>
"""
        
        
        part1 = MIMEText(text, "plain")
        part2 = MIMEText(html, "html")
        message.attach(part1)
        message.attach(part2)
        
        
        if not SMTP_USER or not SMTP_PASSWORD or SMTP_USER == "your-email@example.com":
            print(f"[DEV MODE] Would send OTP {otp} to {email}")
            print(f"[DEV MODE] Configure SMTP credentials in dashboard_secrets.py")
            
            return True
        
        await aiosmtplib.send(
            message,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True
        )
        
        print(f"OTP sent successfully to {email}")
        return True
        
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def mask_email(email: str) -> str:
    """Mask email for display (em***@example.com)."""
    parts = email.split('@')
    if len(parts) != 2:
        return email
    
    username = parts[0]
    domain = parts[1]
    
    if len(username) <= 2:
        masked = username[0] + '*'
    else:
        masked = username[0] + username[1] + '*' * (len(username) - 2)
    
    return f"{masked}@{domain}"
