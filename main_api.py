# --- API core (with auth + debug) ---
import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url, URL

from database.database_user import init_db
from routers.user_router import router as auth_router

app = FastAPI(title="volai-api-02")

# CORS（必要ならあとで許可元を絞る）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _normalize_driver(url: str) -> str:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url

def _get_db_url() -> Optional[str]:
    url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
    return _normalize_driver(url) if url else None

@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception as e:
        import logging
        logging.exception("init_db failed: %s", e)

@app.get("/health")
def health():
    return {"ok": True, "signature": "v2030-min", "has_debug": True}

@app.get("/debug/dbinfo")
def debug_dbinfo():
    url = _get_db_url()
    if not url:
        return {"engine_url": None, "note": "No DATABASE_URL"}
    try:
        u = make_url(url)
        safe = URL.create(
            drivername=u.drivername,
            username=u.username,
            password="***",
            host=u.host, port=u.port,
            database=u.database, query=u.query
        )
        return {"engine_url": str(safe)}
    except Exception as e:
        return {"engine_url": "parse_error", "error": str(e)}

@app.get("/debug/dbping")
def debug_dbping():
    url = _get_db_url()
    if not url:
        return {"error": "No DATABASE_URL set"}
    eng = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    with eng.connect() as conn:
        row = conn.execute(text("select current_database() as db, current_user as user")).mappings().first()
        return {"db": row["db"], "user": row["user"]}

# 認証ルーター（/register, /login, /me）を登録
app.include_router(auth_router)
