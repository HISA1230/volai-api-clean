# api_server.py  ← リポジトリのルート直下に置く
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

app = FastAPI(title="VolAI Minimal API")

origins = (os.getenv("CORS_ORIGINS") or "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

class LoginReq(BaseModel):
    email: str
    password: str

class MagicReq(BaseModel):
    token: str
    email: str | None = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/login")
def login(r: LoginReq):
    if r.email == os.getenv("API_EMAIL") and r.password == os.getenv("API_PASSWORD"):
        return {"access_token": f"DEMO_JWT_FOR_{r.email}"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

def auth(authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token")
    token = authorization.removeprefix("Bearer ")
    if not token.startswith("DEMO_JWT_FOR_"):
        raise HTTPException(status_code=401, detail="Bad token")
    return {"email": token.replace("DEMO_JWT_FOR_", "")}

@app.get("/me")
def me(user=Depends(auth)):
    return user

@app.post("/auth/magic_login")
def magic(r: MagicReq):
    if r.token and r.token == os.getenv("ADMIN_TOKEN"):
        email = r.email or os.getenv("API_EMAIL") or "user@example.com"
        return {"access_token": f"DEMO_JWT_FOR_{email}"}
    raise HTTPException(status_code=403, detail="Invalid magic token")

@app.get("/api/predict/latest")
def latest(n: int = 100, mode: str | None = None):
    return []  # 最小限：UIが落ちない用

from datetime import datetime

@app.get("/api/predict/ping")
def ping():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}