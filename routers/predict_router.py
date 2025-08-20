# routers/predict_router.py
# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import os, joblib, numpy as np, pandas as pd

# ---- Optional: DB 依存（無ければ空で返す） ----
try:
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from database.database_user import get_db
except Exception:
    get_db = None
    Session = None
    text = None

# ---- Optional: 認証（無ければ匿名でも通す） ----
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
    """予測ログ（DBが無ければ空配列）"""
    if not get_db or not db or not text:
        return []
    try:
        rows = db.execute(text("""
            SELECT id, created_at, rci, atr, vix,
                   predicted_volatility AS pred,
                   actual_volatility    AS actual,
                   abs_error, model_path
              FROM prediction_logs
             ORDER BY created_at DESC
             LIMIT 50
        """)).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []

@router.post("/shap/recompute")
def shap_recompute(
    body: ShapRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # ---- shap はここで遅延 import（未インストールなら 501）----
    try:
        import shap  # heavy
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="shap がサーバに入っていません。requirements.txt に 'shap>=0.48' を追加して再デプロイしてください。"
        )

    model_path   = body.model_path or "models/vol_model.pkl"
    feature_cols = body.feature_cols or ["rci", "atr", "vix"]
    sample_size  = int(body.sample_size or 512)

    # ---- X の用意：DB > 合成データ ----
    X = None
    from_db = False
    if get_db and db and text:
        try:
            cols_sql = ", ".join(feature_cols)
            df = pd.DataFrame(
                db.execute(
                    text(f"SELECT {cols_sql} FROM prediction_logs WHERE {feature_cols[0]} IS NOT NULL LIMIT :lim"),
                    {"lim": sample_size}
                ).mappings().all()
            )
            if not df.empty:
                X = df[feature_cols].apply(pd.to_numeric, errors="coerce").dropna()
                from_db = not X.empty
        except Exception:
            pass

    if X is None or X.empty:
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

    # ---- モデル読込 or 代替の軽量モデル ----
    model = None
    try:
        if os.path.exists(model_path):
            model = joblib.load(model_path)
    except Exception:
        model = None

    if model is None:
        from sklearn.ensemble import RandomForestRegressor
        y = (X_use.sum(axis=1) + np.random.default_rng(0).normal(0, 0.1, len(X_use)))
        model = RandomForestRegressor(n_estimators=10, random_state=0)
        model.fit(X_use, y)

    # ---- SHAP 計算＆保存 ----
    explainer = shap.Explainer(model, X_use)
    sv = explainer(X_use)

    base = os.path.splitext(model_path)[0]
    shap_values_path = f"{base}_shap_values.pkl"
    summary_csv_path = f"{base}_shap_summary.csv"
    os.makedirs("models", exist_ok=True)

    joblib.dump(sv, shap_values_path)
    mean_abs = np.abs(sv.values).mean(axis=0)
    summary = pd.DataFrame({"feature": feature_cols, "mean_abs_shap": mean_abs}).sort_values("mean_abs_shap", ascending=False)
    summary.to_csv(summary_csv_path, index=False)
    summary.to_csv("models/shap_summary.csv", index=False)  # 互換

    top5 = list(summary["feature"].head(5))
    return {
        "message": "SHAP recomputed",
        "from_db": from_db,
        "model_path": model_path,
        "shap_values_path": shap_values_path,
        "summary_csv_path": summary_csv_path,
        "top_features": top5,
    }
