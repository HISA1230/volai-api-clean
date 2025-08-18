# --- MINIMAL APP with debug endpoints (v2030-min) ---
import os
from typing import Optional
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url, URL

app = FastAPI(title="volai-api (minimal with debug)")

def _normalize_driver(url: str) -> str:
    # postgres:// → postgresql+psycopg2:// に変換
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url

def _get_db_url() -> Optional[str]:
    url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        return None
    return _normalize_driver(url)

_ENGINE = None
def get_engine():
    global _ENGINE
    if _ENGINE is None:
        url = _get_db_url()
        _ENGINE = create_engine(url, pool_pre_ping=True, pool_recycle=300) if url else None
    return _ENGINE

@app.get("/health")
def health():
    # ← この文字列が見えたら「新しいコード」が動いています
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
    eng = get_engine()
    if not eng:
        return {"error": "No DATABASE_URL set"}
    try:
        with eng.connect() as conn:
            row = conn.execute(text("select current_database() as db, current_user as user")).mappings().first()
            return {"db": row["db"], "user": row["user"]}
    except Exception as e:
        return {"error": f"db connection failed: {e}"}
