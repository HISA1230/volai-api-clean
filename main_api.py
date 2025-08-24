# main_api.py
from dotenv import load_dotenv
load_dotenv()  # .env を自動読込（存在すれば）

import os
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from sqlalchemy import inspect, text

# ==============================
# DBエンジン（/health はDB非依存、/debug は使用）
# ==============================
try:
    from database.database_user import engine
except Exception:
    engine = None

# -----------------------------
# アプリ基本情報
# -----------------------------
APP_NAME = os.getenv("APP_NAME", "Volatility AI API")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
)

# --- JSONレスポンスに charset=utf-8 を強制付与 ---
@app.middleware("http")
async def add_utf8_charset(request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset=" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

# ==============================
# /debug 全体を ADMIN_TOKEN で保護（最終ゲート）
# 空白混入対策で strip() を双方に適用
# ==============================
class AdminTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/debug"):
            admin = (os.getenv("ADMIN_TOKEN") or "").strip()
            if not admin:
                return JSONResponse(status_code=500, content={"detail": "ADMIN_TOKEN not configured"})
            token = (request.headers.get("X-Admin-Token") or "").strip()
            if token != admin:
                return JSONResponse(status_code=403, content={"detail": "admin token required"})
        return await call_next(request)

app.add_middleware(AdminTokenMiddleware)

# -----------------------------
# ログ設定（Renderなら標準出力へ）
# -----------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -----------------------------
# CORS（本番はUIドメインに絞る）
#   例: CORS_ALLOW_ORIGINS="https://your-ui.example.com,https://volai-ui.onrender.com"
# -----------------------------
origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
if origins_env == "*" or origins_env == "":
    allow_origins: List[str] = ["*"]
else:
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# ルーター読込（失敗しても起動は継続）
# -----------------------------
auth_router = models_router = predict_router = scheduler_router = owners_router = None
_AUTH_ERR = _MODELS_ERR = _PREDICT_ERR = _SCHED_ERR = _OWNERS_ERR = None

try:
    from routers import user_router
    auth_router = user_router.router
    app.include_router(auth_router)
except Exception as e:
    _AUTH_ERR = str(e)
    logger.exception("auth(user) router load failed: %s", e)

try:
    from routers import models_router as _models_router
    models_router = _models_router.router
    app.include_router(models_router)
except Exception as e:
    _MODELS_ERR = str(e)
    logger.exception("models router load failed: %s", e)

try:
    from routers import predict_router as _predict_router
    predict_router = _predict_router.router
    app.include_router(predict_router)
except Exception as e:
    _PREDICT_ERR = str(e)
    logger.exception("predict router load failed: %s", e)

try:
    from routers import scheduler_router as _scheduler_router
    scheduler_router = _scheduler_router.router
    app.include_router(scheduler_router)
except Exception as e:
    _SCHED_ERR = str(e)
    logger.exception("scheduler router load failed: %s", e)

# ← ここが今回の追加（owners ルーター）
try:
    from routers import owners_router as _owners_router
    owners_router = _owners_router.router
    app.include_router(owners_router)
except Exception as e:
    _OWNERS_ERR = str(e)
    logger.exception("owners router load failed: %s", e)

# -----------------------------
# ルート & ヘルス
# -----------------------------
@app.get("/")
def root():
    return {
        "ok": True,
        "name": APP_NAME,
        "version": APP_VERSION,
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/health")
def health():
    # シンプル版（DBに触れない）
    return {"ok": True}

# ==============================
# /debug 系（グローバルミドルウェアで保護済み）
# ==============================
@app.get("/debug/ping", summary="Debug Ping (light)")
def debug_ping():
    # 権限/ネット瞬断を切り分ける最軽量のエンドポイント
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/debug/routers", summary="Debug Routers")
def debug_routers():
    return {
        "auth_loaded": bool(auth_router is not None),
        "models_loaded": bool(models_router is not None),
        "predict_loaded": bool(predict_router is not None),
        "scheduler_loaded": bool(scheduler_router is not None),
        "owners_loaded": bool(owners_router is not None),   # 追加
        "auth_error": _AUTH_ERR,
        "models_error": _MODELS_ERR,
        "predict_error": _PREDICT_ERR,
        "scheduler_error": _SCHED_ERR,
        "owners_error": _OWNERS_ERR,                        # 追加
    }

from models.models_user import Base  # テーブル作成用

@app.get("/debug/dbcheck", summary="Debug Dbcheck")
def debug_dbcheck():
    if engine is None:
        return JSONResponse(status_code=500, content={"ok": False, "error": "engine is None (DB not configured)"})
    try:
        insp = inspect(engine)
        return {
            "ok": True,
            "tables": {
                "users": insp.has_table("users"),
                "prediction_logs": insp.has_table("prediction_logs"),
                "model_meta": insp.has_table("model_meta"),
                "model_eval": insp.has_table("model_eval"),
            }
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.post("/debug/dbcreate", summary="Debug Dbcreate")
def debug_dbcreate():
    if engine is None:
        return JSONResponse(status_code=500, content={"ok": False, "error": "engine is None (DB not configured)"})
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True, "created": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/debug/dbinfo", summary="Debug Dbinfo")
def debug_dbinfo():
    try:
        if engine is None:
            raise RuntimeError("engine is None")
        return {"ok": True, "url": engine.url.render_as_string(hide_password=True)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/debug/selftest", summary="Debug Selftest")
def debug_selftest():
    out = {"ok": True}

    # SECRET_KEY の存在チェック
    sk = os.getenv("SECRET_KEY")
    out["secret_key_present"] = bool(sk)
    out["secret_key_len"] = len(sk or "")

    # bcrypt / passlib のバージョン & 動作テスト
    try:
        import bcrypt as _bcrypt
        import passlib, passlib.context
        out["bcrypt_version"] = getattr(_bcrypt, "__version__", None) or "unknown"
        out["passlib_version"] = getattr(passlib, "__version__", None)

        ctx = passlib.context.CryptContext(schemes=["bcrypt"], deprecated="auto")
        h = ctx.hash("test1234")
        out["bcrypt_hash_ok"] = bool(h and ctx.verify("test1234", h))
    except Exception as e:
        out["bcrypt_error"] = f"{type(e).__name__}: {e}"
        out["bcrypt_trace"] = traceback.format_exc()
        out["ok"] = False

    # JWT の生成/検証テスト
    try:
        from jose import jwt
        token = jwt.encode(
            {"sub": "selftest", "exp": datetime.utcnow() + timedelta(minutes=1)},
            sk or "dummy-secret",
            algorithm="HS256",
        )
        data = jwt.decode(token, sk or "dummy-secret", algorithms=["HS256"])
        out["jwt_ok"] = (data.get("sub") == "selftest")
    except Exception as e:
        out["jwt_error"] = f"{type(e).__name__}: {e}"
        out["jwt_trace"] = traceback.format_exc()
        out["ok"] = False

    # DB 接続テスト
    try:
        if engine is None:
            raise RuntimeError("engine is None")
        with engine.connect() as con:
            out["db_select1"] = con.execute(text("SELECT 1")).scalar()
    except Exception as e:
        out["db_error"] = f"{type(e).__name__}: {e}"
        out["db_trace"] = traceback.format_exc()
        out["ok"] = False

    return JSONResponse(out)