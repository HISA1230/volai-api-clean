# routers/predict_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

# DB セッション
from database.database_user import get_db

router = APIRouter(prefix="/predict", tags=["Predict"])

# =========================
# 1) 予測ログ取得（owner フィルタ対応）
# =========================
@router.get("/logs", summary="Get Logs")
def get_logs(
    owner: Optional[str] = Query(None, description="学也 / 練習H / 正恵 / 練習M / 共用"),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    prediction_logs から必要カラムを直接 SQL で取得。
    モデル定義に依存しないので安全（列追加/欠落があっても壊れにくい）。
    """
    base_sql = """
        SELECT
          id,
          created_at,
          sector,
          size,
          time_window,
          pred_vol,
          abs_error,
          comment,
          owner
        FROM prediction_logs
    """
    params: Dict[str, Any] = {}
    if owner:
        base_sql += " WHERE owner = :owner"
        params["owner"] = owner

    base_sql += " ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    rows = db.execute(text(base_sql), params).mappings().all()
    return [dict(r) for r in rows]

# =========================
# 2) SHAP 再計算（既存実装があれば呼ぶ）
# =========================
# 既存の実装が別モジュールにある場合に備えて動的 import
try:
    # 例: services/shap.py に def recompute_shap(db: Session) -> dict: がある想定
    from services.shap import recompute_shap  # type: ignore
except Exception:
    recompute_shap = None  # フォールバックへ

@router.post("/shap/recompute", summary="Shap Recompute")
def shap_recompute(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    - 既存の recompute 実装があればそれを呼ぶ
    - 無ければ models/shap_summary.csv を最低限用意するフォールバック
    """
    if recompute_shap:
        try:
            result = recompute_shap(db=db)  # type: ignore
            if isinstance(result, dict):
                return {"ok": True, **result}
            return {"ok": True, "detail": "recomputed (no dict payload)"}
        except Exception as e:
            # 既存実装で失敗した場合も API は 200 にし、詳細を返す（運用都合）
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # --- フォールバック（既存実装が無い環境向けの最低限動作） ---
    try:
        models_dir = Path("models")
        models_dir.mkdir(exist_ok=True)
        csv_path = models_dir / "shap_summary.csv"
        if not csv_path.exists():
            # 空のサマリ（ヘッダのみ）
            csv_path.write_text("feature,importance\n", encoding="utf-8")
        return {"ok": True, "csv": str(csv_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fallback failed: {type(e).__name__}: {e}")