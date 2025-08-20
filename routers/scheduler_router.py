# routers/scheduler_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# 認証（既存のJWT）
from auth.auth_jwt import get_current_user
from models.models_user import UserModel  # 既存Userモデル

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])

# メモリ内の簡易履歴（Render再起動で消えるがデモ用途として十分）
_STATUS_LOG: List[Dict[str, Any]] = []

class SchedulerRunIn(BaseModel):
    mae_threshold: float = Field(0.008, description="MAE しきい値")
    min_new_labels: Optional[int] = Field(None, description="新規ラベル最小数（Noneで無効）")
    top_k: int = Field(3, description="特徴量Top-K")
    auto_promote: bool = Field(True, description="条件成立時に昇格を反映するか")
    note: Optional[str] = Field(None, description="メモ")

@router.post("/run")
def run_scheduler(
    body: SchedulerRunIn,
    current_user: UserModel = Depends(get_current_user),
):
    """
    条件チェック →（必要なら）昇格 → SHAP再計算、の“体裁”だけ整えた最小スタブ。
    実際のロジックは各自の要件に合わせて差し替えてください。
    """
    # ダミーでモデル2本をチェックした体にする
    checked_models = [
        {
            "model_path": "models/vol_model.pkl",
            "mae": 0.0075,
            "meets_threshold": True,
        },
        {
            "model_path": "models/vol_model_v2.pkl",
            "mae": 0.0091,
            "meets_threshold": False,
        },
    ]

    triggered = []
    # 条件成立＆auto_promote の場合のみ“昇格した体”
    for row in checked_models:
        if row["meets_threshold"] and body.auto_promote:
            triggered.append({
                "model_path": row["model_path"],
                "promoted": True,
                "shap_recomputed": True,   # 実際は /predict/shap/recompute を呼ぶ
            })

    result = {
        "run_at": datetime.utcnow().isoformat() + "Z",
        "by_user": current_user.email,
        "params": body.model_dump(),
        "checked_models": checked_models,
        "triggered": triggered,
    }

    # 履歴に保存（最新が先頭）
    _STATUS_LOG.insert(0, result)
    if len(_STATUS_LOG) > 100:
        _STATUS_LOG.pop()

    return result

@router.get("/status")
def scheduler_status(
    current_user: UserModel = Depends(get_current_user),
):
    """最近の実行履歴を返す（最新が先頭）"""
    return {"value": _STATUS_LOG}
