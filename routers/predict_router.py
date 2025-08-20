# routers/predict_router.py
# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import os
import joblib
import numpy as np
import pandas as pd
import shap

# --- Optional: DB 依存はあれば使う、無ければ素通り ---
try:
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from database.database_user import get_db
except Exception:
    get_db = None
    Session = None
    text = None

# --- Optional: 認証（無ければ匿名で通す） ---
try:
    from auth.auth_jwt import get_current_user
except Exception:
    def get_current_user():
        return {"id": 0, "email": "anon@example.com"}

router = APIRouter(prefix="/predict", tags=["Predict"])

class ShapRequest(BaseModel):
    model_path: Optional[str] = "models/vol_model.pkl"
    sample_size: Optional[int] = 512
    feature_cols: Optional[List[str]] = ["rci", "atr", "vix"]

@router.get("/logs")
def get_prediction_logs(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """予測ログ（あればDBから、無ければ空配列）"""
    if not get_db or not db or not text:
        return []
    try:
        rows = db.execute(
            text(
                """
                SELECT id, created_at, rci, atr, vix,
                       predicted_volatility AS pred,
                       actual_volatility    AS actual,
                       abs_error, model_path
                  FROM prediction_logs
                 ORDER BY created_at DESC
                 LIMIT 50
                """
            )
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []

@router.post("/shap/recompute")
def shap_recompute(
    body: ShapRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    SHAP を再計算して:
      - models/{basename}_shap_values.pkl
      - models/{basename}_shap_summary.csv
    を保存。DBに学習データが無ければ合成データで実行（デモ用）。
    """
    model_path  = body.model_path or "models/vol_model.pkl"
    feature_cols = body.feature_cols or ["rci", "atr", "vix"]
    sample_size  = int(body.sample_size or 512)

    # --- 1) X の用意（DBがあれば使う／無ければ合成） ---
    X = None
    from_db = False
    if get_db and db and text:
        try:
            cols_sql = ", ".join(feature_cols)
            q = text(f"SELECT {cols_sql} FROM prediction_logs WHERE {feature_cols[0]} IS NOT NULL LIMIT :lim")
            df = pd.DataFrame(db.execute(q, {"lim": sample_size}).mappings().all())
            if not df.empty:
                X = df[feature_cols].apply(pd.to_numeric, errors="coerce").dropna()
                from_db = not X.empty
        except Exception:
            from_db = False

    if X is None or X.empty:
        # 合成データ（デモ）
        n = max(64, sample_size)
        rng = np.random.default_rng(42)
        data = {
            "rci": rng.uniform(-100, 100, n),
            "atr": rng.uniform(0, 1, n),
            "vix": rng.uniform(10, 30, n),
        }
        for c in feature_cols:
            if c not in data:
                data[c] = rng.normal(0, 1, n)
        X = pd.DataFrame(data)[feature_cols]

    X_use = X.head(sample_size)

    # --- 2) モデル読込（失敗したら軽量モデルを内製） ---
    model = None
    try:
        if os.path.exists(model_path):
            model = joblib.load(model_path)
    except Exception:
        model = None

    if model is None:
        # 代替の軽量モデル（デモ用）
        try:
            from sklearn.ensemble import RandomForestRegressor
            y = (X_use.sum(axis=1) + np.random.default_rng(0).normal(0, 0.1, len(X_use)))
            model = RandomForestRegressor(n_estimators=10, random_state=0)
            model.fit(X_use, y)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to prepare model: {e}")

    # --- 3) SHAP 計算と保存 ---
    try:
        explainer = shap.Explainer(model, X_use)
        sv = explainer(X_use)

        base = os.path.splitext(model_path)[0]
        shap_values_path = f"{base}_shap_values.pkl"
        summary_csv_path = f"{base}_shap_summary.csv"

        joblib.dump(sv, shap_values_path)

        mean_abs = np.abs(sv.values).mean(axis=0)
        summary = pd.DataFrame({"feature": feature_cols, "mean_abs_shap": mean_abs})
        summary = summary.sort_values("mean_abs_shap", ascending=False)

        os.makedirs("models", exist_ok=True)
        summary.to_csv(summary_csv_path, index=False)
        # 互換: 共通パスにも出力
        summary.to_csv("models/shap_summary.csv", index=False)

        return {
            "message": "SHAP recomputed",
            "from_db": from_db,
            "model_path": model_path,
            "shap_values_path": shap_values_path,
            "summary_csv_path": summary_csv_path,
            "top_features": summary["feature"].head(5).tolist(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SHAP failed: {e}")
