# app/routers/metrics_router.py
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.database.session import session_scope

router = APIRouter()

def _exists(s, t: str) -> bool:
    q = text("""
        select exists (
            select 1 from information_schema.tables
            where table_schema='public' and table_name=:t
        )
    """)
    return bool(s.execute(q, {"t": t}).scalar())

@router.get("/ops/metrics")
def metrics():
    try:
        out = {}
        with session_scope() as s:
            for t in ("macro_daily","news_sentiment","supply_demand"):
                if _exists(s, t):
                    out[t] = int(s.execute(text(f"select count(*) from {t}")).scalar_one())
                else:
                    out[t] = 0
        return out
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"metrics failed: {e}")
    
from fastapi import HTTPException

@router.get("/ops/dbping")
def dbping():
    try:
        with session_scope() as s:
            v = s.execute(text("select 1")).scalar_one()
            db = s.execute(text("select current_database()")).scalar_one()
            return {"ok": True, "one": int(v), "db": db}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"dbping failed: {e}")