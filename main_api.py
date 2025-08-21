# main_api.py
import os
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect

# DBまわり（/health での軽い疎通に備えて import だけ）
try:
    from database.database_user import engine
except Exception:  # DB未設定でもアプリ自体は起動できるように
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
auth_router = models_router = predict_router = scheduler_router = None
_AUTH_ERR = _MODELS_ERR = _PREDICT_ERR = _SCHED_ERR = None

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

# -----------------------------
# デバッグ：どのルーターが載っているか
# -----------------------------
@app.get("/debug/routers")
def debug_routers():
    return {
        "auth_loaded": bool(auth_router is not None),
        "models_loaded": bool(models_router is not None),
        "predict_loaded": bool(predict_router is not None),
        "scheduler_loaded": bool(scheduler_router is not None),
        "auth_error": _AUTH_ERR,
        "models_error": _MODELS_ERR,
        "predict_error": _PREDICT_ERR,
        "scheduler_error": _SCHED_ERR,
    }

# ==============================
# 一時デバッグAPI：DBテーブル確認/作成
# ==============================
from models.models_user import Base  # 既にimport済みなら重複不要だが安全のため

@app.get("/debug/dbcheck")
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

@app.post("/debug/dbcreate")
def debug_dbcreate():
    if engine is None:
        return JSONResponse(status_code=500, content={"ok": False, "error": "engine is None (DB not configured)"})
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True, "created": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})