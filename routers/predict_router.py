# routers/predict_router.py
# -*- coding: utf-8 -*-
from typing import List, Dict, Any
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/predict", tags=["predict"])

# 疎通確認（GET/HEAD）
@router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root_ping():
    return {"ok": True, "router": "predict", "file": __file__}

@router.api_route("/ping", methods=["GET", "HEAD"], include_in_schema=False)
def ping():
    return {"ok": True, "router": "predict", "file": __file__}

# 既存エンドポイント
@router.get("/latest")
def get_latest(n: int = Query(10, ge=1, le=1000)) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(min(n, 5)):
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
            "symbols": ["AAPL", "MSFT"] if i % 2 == 0 else ["XOM"],
        })
    return out