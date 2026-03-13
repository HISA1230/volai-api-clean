# api_server.py  ← リポジトリのルート直下に置く
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

app = FastAPI(title="VolAI Minimal API")

# Render側の env はあなたのサービスでは CORS_ALLOW_ORIGINS を使っていたので両対応
_cors_raw = (os.getenv("CORS_ORIGINS") or os.getenv("CORS_ALLOW_ORIGINS") or "*").strip()
origins = [x.strip() for x in _cors_raw.split(",") if x.strip()]
if not origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Auth (demo)
# ----------------------------
class LoginReq(BaseModel):
    email: str
    password: str

class MagicReq(BaseModel):
    token: str
    email: Optional[str] = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/login")
def login(r: LoginReq):
    # Render env のキーが API_LOGIN_EMAIL / API_LOGIN_PASSWORD の可能性もあるので両対応
    ok_email = (os.getenv("API_EMAIL") or os.getenv("API_LOGIN_EMAIL") or "").strip()
    ok_pass  = (os.getenv("API_PASSWORD") or os.getenv("API_LOGIN_PASSWORD") or "").strip()

    if r.email == ok_email and r.password == ok_pass:
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
    if r.token and r.token == (os.getenv("ADMIN_TOKEN") or "").strip():
        email = (r.email or os.getenv("API_EMAIL") or os.getenv("API_LOGIN_EMAIL") or "user@example.com").strip()
        return {"access_token": f"DEMO_JWT_FOR_{email}"}
    raise HTTPException(status_code=403, detail="Invalid magic token")

# ----------------------------
# Predict (dummy for UI)
# ----------------------------
def _dummy_latest(n: int = 100) -> List[Dict[str, Any]]:
    """DBが空でもUIに表示を出すためのダミー。"""
    now = datetime.utcnow().isoformat() + "Z"
    rows = [
        {
            "ts_utc": now,
            "time_band": "A",
            "sector": "tech",
            "size": "Small",
            "symbol": "NVDA",
            "pred_vol": 0.012,
            "fake_rate": 0.24,
            "confidence": 0.68,
            "rec_action": "WATCH",
            "comment": "DBが空のためダミー表示（確認用）",
        },
        {
            "ts_utc": now,
            "time_band": "A",
            "sector": "energy",
            "size": "Mid",
            "symbol": "XOM",
            "pred_vol": 0.010,
            "fake_rate": 0.18,
            "confidence": 0.72,
            "rec_action": "WATCH",
            "comment": "DBが空のためダミー表示（確認用）",
        },
    ]
    nn = max(1, min(int(n), 1000))
    return rows[:nn]

@app.get("/api/predict/latest")
def latest(n: int = 100, mode: str | None = None):
    # いまはまだDB/推論を繋いでいないのでダミーを返す
    return _dummy_latest(n=n)

@app.get("/api/predict/ping")
def ping():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}
