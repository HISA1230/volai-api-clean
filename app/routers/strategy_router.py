# app/routers/strategy_router.py
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import text
from app.database.session import session_scope

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

@router.get("/latest")
def latest(n: int = Query(30, ge=1, le=200)):
    """
    news_sentiment を ts_utc 降順で n 件返す簡易API。
    Streamlit の最小テーブル表示用。
    """
    try:
        with session_scope() as s:
            rows = s.execute(text("""
                select id, ts_utc, sector, window_hours, avg_score, pos_ratio, volume, symbols, source, meta
                from news_sentiment
                order by ts_utc desc
                limit :n
            """), {"n": n}).mappings().all()
        return {"n": n, "rows": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"strategy.latest failed: {e}")