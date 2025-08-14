# main_api.py
# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv(override=True)  # .env を優先して読み込む

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from routers.user_router import router as user_router
from routers.predict_router import router as predict_router
from routers.models_router import router as models_router
from routers.scheduler_router import router as scheduler_router  # ← prefixはrouter側にあるため、このまま登録でOK

# ---------------- App ----------------
app = FastAPI(
    title="Volatility AI API",
    version="2030",
    description="High-Accuracy Volatility Prediction API (FastAPI + PostgreSQL + AutoML)",
)

# ---------------- CORS ----------------
# ローカル（8502: Streamlit）& Cloudflare Quick Tunnel（毎回URLが変わる）を許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8502",
        "http://127.0.0.1:8502",
    ],
    # ← Render / Streamlit Cloud / Cloudflare Quick Tunnel を全部許可
    allow_origin_regex=r"^https://([a-z0-9-]+\.trycloudflare\.com|.*\.onrender\.com|.*\.streamlit\.app)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- 通知（任意機能） ----------------
from pydantic import BaseModel
from typing import Any, Dict, Optional
from utils.notifier import notify_all
import os

class NotifyBody(BaseModel):
    title: Optional[str] = "🔔 テスト通知"
    payload: Dict[str, Any] = {}

@app.post("/notify/send")
def notify_send(body: NotifyBody):
    try:
        return notify_all(body.title, body.payload)
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"ok": False, "server_error": str(e)}

@app.post("/notify/test")
def notify_test():
    slack = bool(os.getenv("SLACK_WEBHOOK_URL"))
    email = all(os.getenv(k) for k in ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_TO"])
    line  = bool(os.getenv("LINE_TOKEN"))
    return {
        "slack_configured": slack,
        "email_configured": email,
        "line_configured": line,
    }

# ---------------- ルーター登録 ----------------
# ※ scheduler_router 側で prefix="/scheduler" 指定済みなので、ここでは prefix を付けないこと
app.include_router(user_router)
app.include_router(predict_router)
app.include_router(models_router)
app.include_router(scheduler_router)

@app.get("/")
def read_root():
    return {"message": "High-Accuracy Volatility Prediction AI"}

# ---------------- Swagger セキュリティ調整 ----------------
EXCLUDE_SECURITY_PATHS = {"/login", "/register", "/notify/test", "/notify/send", "/debug/env", "/health"}

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    comps = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    comps["BearerAuth"] = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}

    for path, ops in openapi_schema.get("paths", {}).items():
        for _, operation in ops.items():
            if path in EXCLUDE_SECURITY_PATHS:
                operation.pop("security", None)
            else:
                operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ---------------- 環境確認（デバッグ専用） ----------------
@app.get("/debug/env")
def debug_env():
    keys = ["SMTP_HOST","SMTP_PORT","SMTP_SSL","SMTP_USER","SMTP_TO","SMTP_SSL_VERIFY","SMTP_CA_BUNDLE"]
    return {k: os.getenv(k) for k in keys}

# --- ルートにもヘルスチェックを用意（任意） ---
from datetime import datetime, timezone

@app.get("/health")
def root_health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}