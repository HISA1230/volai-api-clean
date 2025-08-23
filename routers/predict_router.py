# routers/predict_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from datetime import datetime

# DBエンジン
from database.database_user import engine

router = APIRouter(prefix="/predict", tags=["Predict"])


def _get_columns(table: str = "prediction_logs") -> set[str]:
    """information_schema から列名一覧を取得"""
    sql = text("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name=:t
    """)
    with engine.connect() as con:
        rows = con.execute(sql, {"t": table}).all()
    return {r[0] for r in rows}


def _build_select_sql(cols: set[str], has_owner_filter: bool) -> str:
    """
    存在する列だけで SELECT を生成。無い列は返さない（後で None 充填）
    返すキーは最終的に: id, created_at, sector, size, time_window, pred_vol, abs_error, comment, owner
    """
    parts: List[str] = ["SELECT id"]

    # created_at が無い環境はない想定だが一応チェック
    if "created_at" in cols:
        parts.append(", created_at")
    else:
        # created_at が無いとORDER BYに困るので保険
        parts.append(", NOW() as created_at")

    # optional列（存在すれば追加、なければ後で None 扱い）
    if "sector" in cols:
        parts.append(", sector")
    if "size" in cols:
        parts.append(", size")
    elif "size_category" in cols:
        parts.append(", size_category AS size")

    if "time_window" in cols:
        parts.append(", time_window")

    if "pred_vol" in cols:
        parts.append(", pred_vol")
    elif "predicted_volatility" in cols:
        parts.append(", predicted_volatility AS pred_vol")

    if "abs_error" in cols:
        parts.append(", abs_error")
    if "comment" in cols:
        parts.append(", comment")
    if "owner" in cols:
        parts.append(", owner")

    parts.append("  FROM prediction_logs")

    where_parts: List[str] = []
    if has_owner_filter and "owner" in cols:
        where_parts.append("owner = :owner")

    if where_parts:
        parts.append(" WHERE " + " AND ".join(where_parts))

    # 並び替え（created_at があればそれ、無ければ id）
    if "created_at" in cols:
        parts.append(" ORDER BY created_at DESC")
    else:
        parts.append(" ORDER BY id DESC")

    parts.append(" LIMIT :limit OFFSET :offset")

    return "\n".join(parts)


def _row_map(row: Any) -> Dict[str, Any]:
    """
    RowMapping -> dict へ。欠けてるキーは None を詰める。
    """
    m = row._mapping
    out = {
        "id": m.get("id"),
        "created_at": m.get("created_at"),
        "sector": m.get("sector") if "sector" in m else None,
        "size": m.get("size") if "size" in m else None,
        "time_window": m.get("time_window") if "time_window" in m else None,
        "pred_vol": m.get("pred_vol") if "pred_vol" in m else None,
        "abs_error": m.get("abs_error") if "abs_error" in m else None,
        "comment": m.get("comment") if "comment" in m else None,
        "owner": m.get("owner") if "owner" in m else None,
    }
    # datetime は ISO に整形（FastAPIでもOKだが明示しておく）
    if isinstance(out["created_at"], datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out


@router.get("/logs", summary="Get Logs")
def get_logs(
    owner: Optional[str] = Query(None, description="所有者フィルタ（例: 共用 / 学也 / 正恵 / 練習H / 練習M）"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    prediction_logs から可変スキーマ対応で取得。
    - 列が存在するものだけ SELECT し、足りない項目は None として返す。
    - owner が指定され、かつ列が存在すれば WHERE で絞り込み。
    """
    cols = _get_columns("prediction_logs")
    sql = _build_select_sql(cols, has_owner_filter=(owner is not None))
    params = {"limit": limit, "offset": offset}
    if owner is not None and "owner" in cols:
        params["owner"] = owner

    try:
        with engine.connect() as con:
            rows = con.execute(text(sql), params).fetchall()
        return [_row_map(r) for r in rows]
    except Exception as e:
        # 失敗時は詳細を返してデバッグしやすく
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "sql": sql,
            "params": params,
        }


# 既存の SHAP 再計算エンドポイントを維持（実装がある前提）
@router.post("/shap/recompute", summary="Shap Recompute")
def shap_recompute():
    # 実装は元のまま/必要に応じて差し戻し
    return {"ok": True, "message": "placeholder (keep existing implementation if you had one)"}