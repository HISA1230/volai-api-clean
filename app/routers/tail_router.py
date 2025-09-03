# app/routers/tail_router.py
from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy import text
from app.database.session import session_scope

router = APIRouter()

def _columns(sess, table: str) -> list[str]:
    q = text("""
        select column_name
        from information_schema.columns
        where table_schema='public' and table_name=:t
        order by ordinal_position
    """)
    return [r[0] for r in sess.execute(q, {"t": table}).fetchall()]

@router.get("/ops/tail/{table}")
def tail(
    table: str = Path(..., description="テーブル名（例: news_sentiment）"),
    n: int = Query(10, ge=1, le=200),
    order_by: str | None = Query(None, description="並べ替え列を明示指定したい場合に使用")
):
    try:
        with session_scope() as s:
            cols = _columns(s, table)
            if not cols:
                raise HTTPException(status_code=404, detail=f"table '{table}' not found")

            ob = order_by
            if ob and ob not in cols:
                raise HTTPException(status_code=400, detail=f"order_by '{ob}' not in columns {cols}")

            if not ob:
                for cand in ("ts_utc", "ts", "timestamp", "created_at", "date", "dt"):
                    if cand in cols:
                        ob = cand
                        break

            if ob:
                q = text(f'SELECT * FROM "{table}" ORDER BY "{ob}" DESC LIMIT :n')
                rows = [dict(r._mapping) for r in s.execute(q, {"n": n}).fetchall()]
            else:
                q = text(f'SELECT * FROM "{table}" LIMIT :n')
                rows = [dict(r._mapping) for r in s.execute(q, {"n": n}).fetchall()]

            return {"table": table, "order_by": ob, "n": n, "count": len(rows), "cols": cols, "rows": rows}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"tail failed for {table}: {e}")