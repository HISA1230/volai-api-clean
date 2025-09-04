# routers/predict_router.py
# -*- coding: utf-8 -*-
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query
from app.auth_guard import API_REQUIRE_JWT, require_user

# JWTが有効なら保護
deps = [Depends(require_user)] if API_REQUIRE_JWT else []

# 既存の本番パスに合わせて /api/predict をprefixにします
router = APIRouter(prefix="/api/predict", tags=["predict"], dependencies=deps)

@router.get("/latest")
def get_latest(n: int = Query(10, ge=1, le=1000)) -> List[Dict[str, Any]]:
    """
    最新の予測を n 件返すダミー実装。
    将来 DB 実装に差し替える想定。
    """
    out: List[Dict[str, Any]] = []
    max_rows = 5  # 制限を外すなら range(n) に変更
    for i in range(min(n, max_rows)):
        out.append({
            "ts_utc": "2025-09-01T00:00:00Z",
            "time_band": "AH",
            "sector": "Tech" if i % 2 == 0 else "Energy",
            "size": "",
            "pred_vol": 0.52,
            "fake_rate": 0.12,
            "confidence": 0.73,
            "comment": "",
            "rec_action": "watch",
            "symbols": ["AAPL","MSFT"] if i % 2 == 0 else ["XOM"],
        })
    return out
