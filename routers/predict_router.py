# routers/predict_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Literal
from datetime import datetime, date, time, timedelta, timezone

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
    """'HH:MM' -> minutes（不正は None）"""
    if not s:
        return None
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None

# ------------------------------------------------------------
# /predict/logs/summary : 集計（owner/sector/size）
# ------------------------------------------------------------
@router.get("/logs/summary", summary="Logs summary (counts) v8")
def logs_summary(
    by: Literal["owner", "sector", "size"] = Query("owner", description="集計軸"),
    owner: Optional[str] = Query(None, description="このownerに限定（例: 共用 / 学也 など）"),
    start: Optional[date] = Query(None, description="開始日 YYYY-MM-DD（ローカル日付）"),
    end:   Optional[date] = Query(None, description="終了日 YYYY-MM-DD（ローカル日付・当日含む）"),
    time_start: Optional[str] = Query(None, pattern=r"^\d{2}:\d{2}$", description="開始時刻 HH:MM（ローカル）"),
    time_end:   Optional[str] = Query(None, pattern=r"^\d{2}:\d{2}$", description="終了時刻 HH:MM（ローカル）"),
    tz_offset: int = Query(0, description="ローカル→UTC の分オフセット（例: JST=540, PDT=-420）"),
):
    """
    ポイント：
    - 日付フィルタは「ローカル日付の範囲」を UTC に変換して created_at と比較
    - 時刻帯フィルタは created_at を tz_offset だけシフトしてローカル時刻帯で判定
    """
    if engine is None:
        raise HTTPException(500, "DB engine not configured")

    cols = _get_columns("prediction_logs")

    # 集計キー
    if by == "owner":
        if "owner" not in cols:
            return []
        key_expr = "COALESCE(owner, '(NA)')"
    elif by == "sector":
        if "sector" not in cols:
            return []
        key_expr = "COALESCE(sector, '(NA)')"
    else:
        if "size" in cols:
            key_expr = "COALESCE(size, '(NA)')"
        elif "size_category" in cols:
            key_expr = "COALESCE(size_category, '(NA)')"
        else:
            return []

    # ローカル日付 → UTC 境界（Python側でISOにして渡す）
    start_utc = None
    end_utc   = None
    if start:
        # ローカル 00:00 を UTC に戻す（ローカル→UTCは tz_offset 分 引く）
        start_utc = datetime.combine(start, time(0, 0), tzinfo=timezone.utc) - timedelta(minutes=tz_offset)
    if end:
        # ローカル 終日（翌日00:00未満）→ UTC（+1日して tz_offset 分 引く）
        end_utc = datetime.combine(end, time(0, 0), tzinfo=timezone.utc) + timedelta(days=1) - timedelta(minutes=tz_offset)

    t1, t2 = _tmin(time_start), _tmin(time_end)

    params: Dict[str, Any] = {"tz_offset": tz_offset}
    where: List[str] = ["1=1"]

    if owner and "owner" in cols:
        where.append("owner = :owner")
        params["owner"] = owner

    if start_utc:
        where.append("created_at >= :start_utc")
        params["start_utc"] = start_utc.isoformat()
    if end_utc:
        where.append("created_at < :end_utc")
        params["end_utc"] = end_utc.isoformat()

    # ローカル分表現：created_at に tz_offset 分を加算（UTC→ローカル）
    minutes_expr = "(" \
        "EXTRACT(HOUR FROM (created_at + (:tz_offset * INTERVAL '1 minute')))::int * 60 + " \
        "EXTRACT(MINUTE FROM (created_at + (:tz_offset * INTERVAL '1 minute')))::int" \
    ")"

    if t1 is not None and t2 is not None:
        if t1 <= t2:
            where.append(f"{minutes_expr} BETWEEN :t1 AND :t2")
        else:
            # 日跨ぎ（例: 23:00〜01:00）
            where.append(f"({minutes_expr} >= :t1 OR {minutes_expr} <= :t2)")
        params["t1"], params["t2"] = t1, t2

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