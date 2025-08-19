# routers/predict_router.py
# -*- coding: utf-8 -*-
import os
import csv
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# 認証（/login のトークン）
from routers.user_router import get_current_user

router = APIRouter(prefix="/predict", tags=["Predict"])

class ShapRecomputeBody(BaseModel):
    model_path: str = Field(..., description="例: models/vol_model.pkl")
    sample_size: Optional[int] = Field(256, ge=1, description="ダミーなので何でもOK")
    feature_cols: Optional[List[str]] = Field(default=["rci", "atr", "vix"])

@router.post("/shap/recompute")
def shap_recompute(body: ShapRecomputeBody, user = Depends(get_current_user)):
    if not os.path.exists(body.model_path):
        raise HTTPException(status_code=404, detail=f"model not found: {body.model_path}")

    base, _ = os.path.splitext(body.model_path)
    shap_values_path = base + "_shap_values.pkl"   # ダミー
    summary_csv_path = base + "_shap_summary.csv"  # UI が参照

    os.makedirs(os.path.dirname(summary_csv_path), exist_ok=True)
    rows = [
        ["feature", "mean_abs_shap"],
        ["rci", 0.0123],
        ["atr", 0.0101],
        ["vix", 0.0095],
        ["sma5", 0.0077],
        ["sma25", 0.0066],
    ]
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    return {
        "message": "SHAP summary saved (dummy)",
        "model_path": body.model_path,
        "sample_size": body.sample_size,
        "top_features": [r[0] for r in rows[1:3]],
        "shap_values_path": shap_values_path,
        "summary_csv_path": summary_csv_path,
        "at": datetime.utcnow().isoformat() + "Z",
    }
