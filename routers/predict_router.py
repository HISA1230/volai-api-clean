# routers/predict_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

# DBエンジン（安全にインポート）
try:
    from database.database_user import engine
except Exception:
    engine = None  # type: ignore

router = APIRouter(prefix="/predict", tags=["Predict"])


# ------------------------------------------------------------
# モデルパス解決（将来の推論/SHAP用。いまは /logs では未使用）
# ------------------------------------------------------------
def _resolve_model_path(owner: str | None, explicit_path: str | None) -> str:
    """優先順位: 明示指定 > ownerの既定 > グローバル既定 > models フォルダ先頭"""
    # 1) 明示指定
    if explicit_path:
        return explicit_path.strip()

    # 2) owner の既定
    if engine is not None and owner:
        with engine.connect() as con:
            row = con.execute(
                text("SELECT default_model FROM owner_settings WHERE owner=:o"),
                {"o": owner},
            ).fetchone()
        if row and row[0]:
            return str(row[0])

    # 3) グローバル既定（.default_model.txt）
    df = Path("models/.default_model.txt")
    if df.exists():
        p = df.read_text(encoding="utf-8").strip()
        if p:
            return p

    # 4) 最後の砦: models/*.pkl の先頭
    pkls = sorted(Path("models").glob("*.pkl"))
    if pkls:
        return pkls[0].as_posix()

    raise HTTPException(status_code=500, detail="No model available")


# ------------------------------------------------------------
# 可変スキーマ対応のログ取得
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


def _build_select_sql(cols: Set[str], has_owner_filter: bool) -> str:
    """
    存在する列だけで SELECT を生成。無い列は返さない（後で None 充填）。
    返すキーは最終的に: id, created_at, sector, size, time_window, pred_vol, abs_error, comment, owner
    """
    parts: List[str] = ["SELECT id"]

    # created_at が無い環境はない想定だが一応ケア
    if "created_at" in cols:
        parts.append(", created_at")
    else:
        parts.append(", NOW() AS created_at")

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
    """RowMapping -> dict。欠けてるキーは None を詰める。"""
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
    if engine is None:
        return {"ok": False, "error": "engine is None (DB not configured)"}

    try:
        cols = _get_columns("prediction_logs")
        sql = _build_select_sql(cols, has_owner_filter=(owner is not None))
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if owner is not None and "owner" in cols:
            params["owner"] = owner

        with engine.connect() as con:
            rows = con.execute(text(sql), params).fetchall()
        return [_row_map(r) for r in rows]
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            # デバッグ用に発行SQLも返す
            "sql": locals().get("sql"),
            "params": locals().get("params"),
        }

# ---- ここから追加：ログサマリー ----
from fastapi import HTTPException

@router.get("/logs/summary", summary="Logs summary (counts)")
def logs_summary(
    owner: Optional[str] = Query(None, description="このownerに限定（例: 共用 / 学也 など）"),
    by: Optional[str] = Query(
        None,
        description="グルーピング列: owner / sector / size / time_window（未指定なら owner→sector→size の順に自動選択）",
    ),
):
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not configured")

    cols = _get_columns("prediction_logs")

    # size は size / size_category どちらにも対応
    def resolve_group_expr(by_val: Optional[str]) -> Optional[str]:
        if not by_val:
            # デフォルトの優先順位
            for cand in ("owner", "sector", "size", "time_window"):
                ge = resolve_group_expr(cand)
                if ge:
                    return ge
            return None

        if by_val == "size":
            if "size" in cols:
                return "size"
            if "size_category" in cols:
                return "size_category"
            return None

        # それ以外はそのまま列があれば使う
        return by_val if by_val in cols else None

    group_expr = resolve_group_expr(by)

    # WHERE 句
    where_sql = ""
    params: Dict[str, Any] = {}
    if owner is not None and "owner" in cols:
        where_sql = "WHERE owner = :owner"
        params["owner"] = owner

    from sqlalchemy import text as _t

    with engine.connect() as con:
        if group_expr:
            sql = f"""
                SELECT {group_expr} AS key, COUNT(*) AS count
                  FROM prediction_logs
                  {where_sql}
                 GROUP BY {group_expr}
                 ORDER BY COUNT(*) DESC, {group_expr} NULLS LAST
            """
            rows = con.execute(_t(sql), params).all()
            return [{"key": r[0], "count": int(r[1])} for r in rows]
        else:
            # グループ化できる列がない or テーブル最小構成
            sql = f"SELECT COUNT(*) FROM prediction_logs {where_sql}"
            n = con.execute(_t(sql), params).scalar() or 0
            return {"count": int(n)}
# ---- 追加 ここまで ----

# 既存の SHAP 再計算エンドポイントがある前提なら維持
@router.post("/shap/recompute", summary="Shap Recompute")
def shap_recompute():
    # ここは必要に応じて元の実装に差し戻してください
    return {"ok": True, "message": "placeholder (keep existing implementation if you had one)"}