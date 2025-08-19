# routers/predict_router.py
# -*- coding: utf-8 -*-
import os
import time
import random
from typing import List, Optional

import joblib
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# 既存の認証関数を流用（authパッケージが無い構成のため）
from routers.user_router import get_current_user

router = APIRouter(prefix="/predict", tags=["Predict"])

class ShapRecomputeBody(BaseModel):
    model_path: str
    sample_size: Optional[int] = 512
    feature_cols: Optional[List[str]] = None

@router.post("/shap/recompute")
def shap_recompute(body: ShapRecomputeBody, current_user: dict = Depends(get_current_user)):
    """
    SHAPを再計算して保存（まずはUI連携のためのダミー実装）
    - <model>_shap_values.pkl
    - <model>_shap_summary.csv
    を生成します。
    """
    mp = body.model_path
    if not os.path.exists(mp):
        raise HTTPException(status_code=404, detail=f"Model not found: {mp}")

    base = os.path.splitext(mp)[0]
    shap_values_path = f"{base}_shap_values.pkl"
    summary_csv_path  = f"{base}_shap_summary.csv"

    # 本番では実データからSHAP計算に置き換え
    feats = body.feature_cols or [
        "rci", "atr", "vix", "us10y_yield", "vix_term", "sp500_futures_overnight"
    ]
    vals = [abs(random.gauss(0.02, 0.01)) for _ in feats]
    df = pd.DataFrame({"feature": feats, "mean_abs_shap": vals}).sort_values(
        "mean_abs_shap", ascending=False
    )

    os.makedirs(os.path.dirname(mp) or ".", exist_ok=True)
    joblib.dump({"note": "dummy shap values", "ts": time.time()}, shap_values_path)
    df.to_csv(summary_csv_path, index=False, encoding="utf-8")

    return {
        "message": "SHAP summary written (dummy)",
        "shap_values_path": shap_values_path.replace("\\", "/"),
        "summary_csv_path": summary_csv_path.replace("\\", "/"),
        "top_features": df.head(5)["feature"].tolist()
    }

@router.get("/logs")
def predict_logs(current_user: dict = Depends(get_current_user)):
    """
    UI側のMAE比較が空で落ちないように、ダミーの予測ログを返す。
    本番では DB の prediction_logs から返す想定。
    """
    return [
        {"model_path": "models/vol_model.pkl",  "abs_error": 0.012, "created_at": "2025-08-01T09:30:00Z"},
        {"model_path": "models/vol_model_v2.pkl","abs_error": 0.009, "created_at": "2025-08-01T13:00:00Z"},
    ]
