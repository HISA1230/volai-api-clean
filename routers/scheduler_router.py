# routers/scheduler_router.py
# -*- coding: utf-8 -*-
import os
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

# 既存の認証関数を流用
from routers.user_router import get_current_user

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])

HIST_PATH = os.path.join("data", "scheduler_history.json")
os.makedirs("data", exist_ok=True)
if not os.path.exists(HIST_PATH):
    with open(HIST_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)

class RunBody(BaseModel):
    mae_threshold: float = 0.008
    min_new_labels: int = 10
    top_k: int = 3
    auto_promote: bool = True
    note: Optional[str] = "manual run"

@router.post("/run")
def scheduler_run(body: RunBody, current_user: dict = Depends(get_current_user)):
    """
    スケジューラのドライラン（まずはUI連携のためのダミー実装）。
    実行履歴を data/scheduler_history.json に追記します。
    """
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "params": body.dict(),
        "result": {"message": "dry-run (dummy)", "promoted": bool(body.auto_promote)},
    }
    try:
        with open(HIST_PATH, "r", encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = []
    hist.append(rec)
    with open(HIST_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    return {"ok": True, "saved": True, "record": rec}

@router.get("/status")
def scheduler_status(current_user: dict = Depends(get_current_user)):
    """
    直近のスケジューラ実行履歴を返す。
    """
    try:
        with open(HIST_PATH, "r", encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = []
    return {"ok": True, "value": hist[-50:]}  # 直近50件
