# routers/predict_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

# DBエンジン（既存のものを利用）
from database.database_user import engine

router = APIRouter(prefix="/predict", tags=["Predict"])


@router.get("/logs", summary="Get Logs")
def get_logs(
    owner: Optional[str] = Query(
        None,
        description="所有者フィルタ（例: 学也 / 正恵 / 練習H / 練習M / 共用）。未指定なら全件。"
    ),
    limit: int = Query(100, ge=1, le=1000, description="返す件数（1〜1000）"),
    offset: int = Query(0, ge=0, description="スキップ件数（ページング用）"),
):
    """
    prediction_logs から必要カラムだけ取り出す素朴SQL。
    owner が NULL のときは全件、指定時は owner 一致だけに絞る。
    """
    sql = """
        SELECT id, created_at, sector, size, time_window, pred_vol, abs_error, comment
          FROM prediction_logs
         WHERE (:owner IS NULL OR owner = :owner)
         ORDER BY created_at DESC
         LIMIT :limit OFFSET :offset
    """
    try:
        with engine.connect() as con:
            rows = con.execute(
                text(sql),
                {"owner": owner, "limit": limit, "offset": offset},
            ).mappings().all()
        # そのまま配列で返す（以前の出力形式に合わせる）
        return [dict(r) for r in rows]
    except Exception as e:
        # 失敗内容をJSONで返して原因を見える化（当面のデバッグ用）
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@router.post("/shap/recompute", summary="Shap Recompute")
def shap_recompute():
    # 本番実装が未完でも落ちないようにダミー
    return {"ok": True, "message": "noop"}