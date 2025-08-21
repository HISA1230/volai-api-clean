# routers/predict_router.py
# 本実装版: SHAPがあればSHAP、無ければ簡易重要度で shap_summary.csv を再生成

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Dict, Any
import os, pathlib, pickle

import pandas as pd

from database.database_user import get_db
from models.models_user import PredictionLog

router = APIRouter(prefix="/predict", tags=["Predict"])

def _load_recent_features(db: Session, limit: int = 500) -> pd.DataFrame:
    rows = (
        db.query(
            PredictionLog.rci,
            PredictionLog.atr,
            PredictionLog.vix,
        )
        .order_by(desc(PredictionLog.created_at))
        .limit(limit)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["rci", "atr", "vix"])
    df = pd.DataFrame(rows, columns=["rci", "atr", "vix"])
    return df.dropna()

def _try_shap_imports():
    try:
        import shap  # type: ignore
        import numpy as np  # type: ignore
        return shap, np
    except Exception:
        return None, None

def _try_load_model(model_path: str):
    try:
        with open(model_path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None

@router.get("/logs")
def get_logs(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    items = (
        db.query(
            PredictionLog.id,
            PredictionLog.created_at,
            PredictionLog.sector,
            PredictionLog.size_category,
            PredictionLog.time_window,
            PredictionLog.predicted_volatility,
            PredictionLog.abs_error,
            PredictionLog.comment,
        )
        .order_by(desc(PredictionLog.created_at))
        .limit(200)
        .all()
    )
    out = []
    for r in items:
        out.append(
            {
                "id": r[0],
                "created_at": r[1].isoformat() if r[1] else None,
                "sector": r[2],
                "size": r[3],
                "time_window": r[4],
                "pred_vol": r[5],
                "abs_error": r[6],
                "comment": r[7],
            }
        )
    return out

@router.post("/shap/recompute")
def shap_recompute(db: Session = Depends(get_db)) -> Dict[str, Any]:
    model_path = os.getenv("MODEL_PATH", "models/vol_model.pkl")
    out_path = pathlib.Path(os.getenv("SHAP_SAVE_PATH", "models/shap_summary.csv"))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = _load_recent_features(db, limit=500)
    if df.empty:
        return {
            "message": "no data to compute (prediction_logs empty)",
            "rows": 0,
            "saved_path": str(out_path),
            "shap_used": False,
        }

    shap, np = _try_shap_imports()
    used_shap = False
    importance: Dict[str, float]

    if shap is not None and np is not None:
        model = _try_load_model(model_path)
        if model is not None:
            try:
                explainer = shap.Explainer(model, df, feature_names=df.columns.tolist())
                sv = explainer(df)
                mean_abs = np.mean(np.abs(sv.values), axis=0)
                importance = dict(zip(df.columns.tolist(), [float(x) for x in mean_abs]))
                used_shap = True
            except Exception:
                # SHAP失敗時はフォールバック
                used_shap = False

    if not used_shap:
        # フォールバック: 特徴量の絶対値平均（簡易指標）
        importance = df.abs().mean().to_dict()  # type: ignore

    # 保存（feature,importance の2列）
    pd.Series(importance).sort_values(ascending=False).rename("importance").to_csv(out_path, header=True)

    return {
        "message": "recomputed",
        "rows": int(len(df)),
        "saved_path": str(out_path),
        "shap_used": bool(used_shap),
        "model_path": model_path if used_shap else None,
        "features": list(df.columns),
    }