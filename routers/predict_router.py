# routers/predict_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Literal
from datetime import datetime, date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

# ------------------------------------------------------------
# DBエンジン（安全にインポート）
# ------------------------------------------------------------
try:
    from database.database_user import engine
except Exception:
    engine = None  # type: ignore

# ------------------------------------------------------------
# ルーター
# ------------------------------------------------------------
router = APIRouter(prefix="/predict", tags=["Predict"])

# ------------------------------------------------------------
# 可変スキーマ対応ユーティリティ
# ------------------------------------------------------------
def _get_columns(table: str = "prediction_logs") -> Set[str]:
    """information_schema から列名一覧を取得"""
    if engine is None:
        raise RuntimeError("DB engine not configured")

    sql = text("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name=:t
    """)
    with engine.connect() as con:
        rows = con.execute(sql, {"t": table}).all()
    return {r[0] for r in rows}

def _tmin(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None

# ------------------------------------------------------------
# /predict/logs/summary : 集計（owner/sector/size）— ★ここが本題
# ------------------------------------------------------------
@router.get("/logs/summary", summary="Logs summary (counts) v6")
def logs_summary(
    by: Literal["owner", "sector", "size"] = Query("owner", description="集計軸"),
    owner: Optional[str] = Query(None, description="このownerに限定（例: 共用 / 学也 など）"),
    start: Optional[date] = Query(None, description="開始日 YYYY-MM-DD"),
    end:   Optional[date] = Query(None, description="終了日 YYYY-MM-DD（当日を含む）"),
    time_start: Optional[str] = Query(None, pattern=r"^\d{2}:\d{2}$", description="開始時刻 HH:MM（例 09:30）"),
    time_end:   Optional[str] = Query(None, pattern=r"^\d{2}:\d{2}$", description="終了時刻 HH:MM（例 15:00）"),
):
    if engine is None:
        raise HTTPException(500, "DB engine not configured")

    cols = _get_columns("prediction_logs")

    # 集計キーの式
    if by == "owner":
        if "owner" not in cols:
            return []
        key_expr = "COALESCE(owner, '(NA)')"
    elif by == "sector":
        if "sector" not in cols:
            return []
        key_expr = "COALESCE(sector, '(NA)')"
    else:  # size
        if "size" in cols:
            key_expr = "COALESCE(size, '(NA)')"
        elif "size_category" in cols:
            key_expr = "COALESCE(size_category, '(NA)')"
        else:
            return []

    params: Dict[str, Any] = {}
    where = ["1=1"]

    if owner and "owner" in cols:
        where.append("owner = :owner")
        params["owner"] = owner

    if start:
        where.append("created_at >= (:start)::timestamptz")
        params["start"] = start.isoformat()

    if end:
        # 当日を含める（< end+1day）
        where.append("created_at < ((:end)::date + interval '1 day')::timestamptz")
        params["end"] = end.isoformat()

    # 時刻（DBタイムゾーン基準, 日跨ぎ対応）
    t1 = _tmin(time_start)
    t2 = _tmin(time_end)
    if t1 is not None and t2 is not None:
        m_expr = "(EXTRACT(HOUR FROM created_at)::int * 60 + EXTRACT(MINUTE FROM created_at)::int)"
        if t1 <= t2:
            where.append(f"{m_expr} BETWEEN :t1 AND :t2")
        else:
            where.append(f"({m_expr} >= :t1 OR {m_expr} <= :t2)")
        params["t1"] = t1
        params["t2"] = t2

    sql = f"""
        SELECT {key_expr} AS key, COUNT(*)::bigint AS count
          FROM prediction_logs
         WHERE {' AND '.join(where)}
         GROUP BY 1
         ORDER BY count DESC, key ASC
    """

    try:
        with engine.connect() as con:
            rows = con.execute(text(sql), params).mappings().all()
        return [{"key": r["key"], "count": int(r["count"])} for r in rows]
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "sql": sql, "params": params}