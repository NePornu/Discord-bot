from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import json
import asyncio
import datetime
import httpx
import uuid
import os

from web.backend.common_web import (
    SECRET_KEY, SESSION_EXPIRY_HOURS, ADMIN_USER_IDS,
    templates, require_auth, require_admin,
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI_BASE,
    DISCORD_TOKEN_URL, DISCORD_API_BASE, DISCORD_AUTH_URL, BOT_TOKEN
)
from shared.redis_client import get_redis_client
from web.backend.generator_utils import generate_local_scenario, BASE_TEMPLATES

app = FastAPI(title="Training Ground", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="training_session", max_age=SESSION_EXPIRY_HOURS * 3600)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[Training] REQUEST: {request.method} {request.url.path}")
    return await call_next(request)

# --- BACKGROUND GENERATOR ---
async def background_scenario_generator():
    await asyncio.sleep(5)
    while True:
        try:
            r = await get_redis_client()
            generated_any = False
            for template_idx in range(6):
                pool_key = f"training:scenario_pool:{template_idx}"
                pool_size = await r.llen(pool_key)
                if pool_size < 50:
                    scenario = await generate_local_scenario(template_idx)
                    if "error" not in scenario:
                        await r.rpush(pool_key, json.dumps(scenario))
                        generated_any = True
                        break
            if not generated_any: await asyncio.sleep(30)
            else: await asyncio.sleep(2)
            await r.close()
        except Exception as e:
            print(f"[AI Generator] Loop Error: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    r = await get_redis_client()
    existing_count = await r.hlen("training:custom_scenarios")
    if existing_count == 0:
        for i, template in enumerate(BASE_TEMPLATES):
            t_copy = template.copy()
            t_copy["id"] = f"base_scenario_{i}"
            await r.hset("training:custom_scenarios", t_copy["id"], json.dumps(t_copy))
    await r.close()
    asyncio.create_task(background_scenario_generator())

# --- BASE ROUTES ---
@app.get("/")
async def home(request: Request):
    if not request.session.get("authenticated"):
        return templates.TemplateResponse("training_login.html", {"request": request})
    return RedirectResponse(url="/training")

@app.get("/login")
async def login(request: Request):
    state = "training"
    redirect_uri = DISCORD_REDIRECT_URI_BASE.replace(":8092", ":8093")
    params = {
        "client_id": DISCORD_CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": "identify", "state": state
    }
    return RedirectResponse(url=f"{DISCORD_AUTH_URL}?" + "&".join(f"{k}={v}" for k, v in params.items()))

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None):
    if not code: return RedirectResponse(url="/login")
    redirect_uri = DISCORD_REDIRECT_URI_BASE.replace(":8092", ":8093")
    async with httpx.AsyncClient() as client:
        t_resp = await client.post(DISCORD_TOKEN_URL, data={
            "client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri
        })
        if t_resp.status_code != 200: return RedirectResponse(url="/login")
        token_data = t_resp.json()
        u_resp = await client.get(f"{DISCORD_API_BASE}/users/@me", headers={"Authorization": f"Bearer {token_data['access_token']}"})
        user_data = u_resp.json()
    
    r = await get_redis_client()
    uid = str(user_data["id"])
    dynamic_admins = await r.smembers("training:admins")
    is_admin = int(uid) in ADMIN_USER_IDS or uid in [a.decode() if isinstance(a, bytes) else str(a) for a in dynamic_admins]
    request.session.update({"authenticated": True, "login_time": datetime.datetime.now().isoformat(),
                            "discord_user": {"id": uid, "username": user_data.get("global_name") or user_data["username"], "avatar": user_data.get("avatar")},
                            "role": "admin" if is_admin else "trainee"})
    return RedirectResponse(url="/training")

@app.get("/training", response_class=HTMLResponse)
async def training_page(request: Request, _=Depends(require_auth)):
    user = request.session.get("discord_user")
    is_admin = request.session.get("role") == "admin"
    return templates.TemplateResponse("training.html", {
        "request": request,
        "user": user,
        "is_admin": is_admin
    })

# --- TRAINING API ---
@app.get("/api/training/scenarios")
async def get_training_scenarios(request: Request):
    course_id = request.query_params.get("course_id")
    r = await get_redis_client()
    raw = await r.hgetall("training:custom_scenarios")
    await r.close()
    
    scenarios = []
    if raw:
        for s_json in raw.values():
            s = json.loads(s_json)
            # If course_id is provided, filter by it. 
            # If not provided (admin view), return all.
            if course_id:
                if str(s.get("course_id")) == str(course_id):
                    scenarios.append(s)
            else:
                scenarios.append(s)
    
    return JSONResponse(content={"scenarios": scenarios})

@app.get("/api/training/history")
async def get_training_history(request: Request):
    user = request.session.get("discord_user")
    if not user: return JSONResponse(content={"error": "K přístupu k historii se musíte přihlásit."}, status_code=401)
    r = await get_redis_client()
    raw = await r.lrange(f"training:results:{user['id']}", 0, -1)
    await r.close()
    return JSONResponse(content={"history": [json.loads(h) for h in raw] if raw else []})

@app.get("/api/training/courses")
async def get_training_courses(request: Request):
    user = request.session.get("discord_user")
    r = await get_redis_client()
    user_id = str(user["id"]) if user else None
    dynamic_admins = await r.smembers("training:admins")
    is_admin = user_id and (int(user_id) in ADMIN_USER_IDS or user_id in [a.decode() if isinstance(a, bytes) else str(a) for a in dynamic_admins])
    courses_raw = await r.hgetall("training:courses")
    courses = [json.loads(c) for c in courses_raw.values()] if courses_raw else []
    
    if is_admin: return JSONResponse(content={"courses": courses})
    if not user: return JSONResponse(content={"courses": [c for c in courses if "guest" in c.get("allowed_roles", [])]})
    
    rights_raw = await r.hget("training:user_rights", user_id)
    rights = json.loads(rights_raw) if rights_raw else {"roles": ["default"]}
    await r.close()
    return JSONResponse(content={"courses": [c for c in courses if any(role in c.get("allowed_roles", []) for role in rights.get("roles", []))]})

@app.post("/api/evaluate-training")
async def evaluate_training(request: Request, _=Depends(require_auth)):
    body = await request.json()
    user_reply = body.get("user_reply", "")
    scenario_data = body.get("scenario", {})
    from web.backend.evaluation_engine import evaluate_reply
    eval_data = evaluate_reply(user_reply, scenario_data)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("http://172.22.0.1:11434/api/generate", json={
                "model": "nepornu-expert", "prompt": f"Jednou větou okomentuj: \"{user_reply[:200]}\"", "stream": False, "options": {"num_predict": 80}
            })
            if resp.status_code == 200: eval_data["ai_comment"] = resp.json().get("response", "").strip()[:200]
    except: pass
    user = request.session.get("discord_user")
    if user:
        r = await get_redis_client()
        entry = {"scenario_id": body.get("scenario_id"), "user_reply": user_reply, "evaluation": eval_data, 
                 "timestamp": datetime.datetime.now().isoformat(), "user": user}
        await r.rpush(f"training:results:{user['id']}", json.dumps(entry))
        await r.sadd("training:users", user["id"])
        await r.close()
    return JSONResponse(content={"evaluation": eval_data})

# --- ADMIN API ---
@app.post("/api/training/admin/courses", dependencies=[Depends(require_admin)])
async def admin_save_course(request: Request):
    c = await request.json()
    if not c.get("id"): c["id"] = str(uuid.uuid4())
    r = await get_redis_client()
    await r.hset("training:courses", c["id"], json.dumps(c))
    await r.close()
    return JSONResponse(content={"success": True, "id": c["id"]})

@app.delete("/api/training/admin/courses/{course_id}", dependencies=[Depends(require_admin)])
async def admin_delete_course(course_id: str):
    r = await get_redis_client()
    await r.hdel("training:courses", course_id)
    await r.close()
    return JSONResponse(content={"success": True})

@app.get("/api/training/admin/users", dependencies=[Depends(require_admin)])
async def admin_get_users(request: Request):
    r = await get_redis_client()
    uids = await r.smembers("training:users")
    dynamic_admins = await r.smembers("training:admins")
    dynamic_str_list = [a.decode() if isinstance(a, bytes) else str(a) for a in dynamic_admins]
    users_list = []
    for uid_bytes in uids:
        uid = uid_bytes.decode() if isinstance(uid_bytes, bytes) else str(uid_bytes)
        rights_raw = await r.hget("training:user_rights", uid)
        history_all = await r.lrange(f"training:results:{uid}", 0, -1)
        history = [json.loads(h) for h in history_all] if history_all else []
        latest = history[-1] if history else {}
        scores = [h.get("evaluation", {}).get("score", 0) for h in history if h.get("evaluation")]
        users_list.append({
            "id": uid, "username": latest.get("user", {}).get("username", f"User {uid}"),
            "roles": json.loads(rights_raw).get("roles", []) if rights_raw else ["default"],
            "exercise_count": len(history), "avg_score": round(sum(scores)/len(scores),1) if scores else 0,
            "last_activity": latest.get("timestamp", "Never"), "is_admin": int(uid) in ADMIN_USER_IDS or uid in dynamic_str_list
        })
    await r.close()
    return JSONResponse(content={"users": users_list})

@app.post("/api/training/admin/users/promote", dependencies=[Depends(require_admin)])
async def admin_promote(request: Request):
    body = await request.json()
    r = await get_redis_client()
    await r.sadd("training:admins", str(body.get("user_id")))
    await r.close()
    return JSONResponse(content={"success": True})

@app.post("/api/training/admin/users/demote", dependencies=[Depends(require_admin)])
async def admin_demote(request: Request):
    body = await request.json()
    uid = str(body.get("user_id"))
    if int(uid) in ADMIN_USER_IDS: return JSONResponse(content={"error": "Cannot demote hardcoded admin"}, status_code=400)
    r = await get_redis_client()
    await r.srem("training:admins", uid)
    await r.close()
    return JSONResponse(content={"success": True})

@app.post("/api/training/admin/users/rights", dependencies=[Depends(require_admin)])
async def admin_set_rights(request: Request):
    body = await request.json()
    r = await get_redis_client()
    await r.hset("training:user_rights", str(body.get("user_id")), json.dumps({"roles": body.get("roles", ["default"])}))
    await r.close()
    return JSONResponse(content={"success": True})

@app.post("/api/training/admin/save-scenario", dependencies=[Depends(require_admin)])
async def admin_save_scenario(request: Request):
    s = await request.json()
    if not s.get("id"): s["id"] = str(uuid.uuid4())
    r = await get_redis_client()
    await r.hset("training:custom_scenarios", s["id"], json.dumps(s))
    await r.close()
    return JSONResponse(content={"success": True, "id": s["id"]})

@app.delete("/api/training/admin/scenarios/{scenario_id}", dependencies=[Depends(require_admin)])
async def admin_delete_scenario(scenario_id: str):
    r = await get_redis_client()
    await r.hdel("training:custom_scenarios", scenario_id)
    await r.close()
    return JSONResponse(content={"success": True})
