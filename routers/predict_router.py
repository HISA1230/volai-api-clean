from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from auth.auth_jwt import get_current_user
from database.database_user import get_db
from models.models_user import PredictionLog, UserModel
from automl.auto_trainer import AutoTrainer
import joblib, os, traceback, numpy as np, pandas as pd
import lightgbm as lgb
import shap

router = APIRouter(prefix="/predict", tags=["Prediction"])

# =========================
# 入力モデル
# =========================
class PredictionInput(BaseModel):
    rci: float
    atr: float
    vix: float
    model_path: str = "models/vol_model.pkl"
    sector: str | None = None
    time_window: str | None = None
    size_category: str | None = None
    comment: str | None = None

# =========================
# 予測
# =========================
@router.post("")
def predict_volatility(
    features: PredictionInput,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        X_input = np.array([[features.rci, features.atr, features.vix]])
        model_path = features.model_path

        if not os.path.exists(model_path):
            raise HTTPException(status_code=500, detail="Model file not found.")
        model = joblib.load(model_path)
        predicted_vol = float(model.predict(X_input)[0])

        new_log = PredictionLog(
            user_id=current_user.id,
            rci=features.rci,
            atr=features.atr,
            vix=features.vix,
            predicted_volatility=predicted_vol,
            model_path=model_path,
            status="success",
            sector=features.sector,
            time_window=features.time_window,
            size_category=features.size_category,
            comment=features.comment,
        )
        db.add(new_log)
        db.commit()

        return {"predicted_volatility": predicted_vol}

    except Exception as e:
        new_log = PredictionLog(
            user_id=current_user.id,
            rci=features.rci,
            atr=features.atr,
            vix=features.vix,
            predicted_volatility=None,
            model_path=features.model_path,
            status="error",
            error_message=str(e),
            sector=features.sector,
            time_window=features.time_window,
            size_category=features.size_category,
            comment=features.comment,
        )
        db.add(new_log)
        db.commit()

        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[Predict Error]\n{traceback.format_exc()}\n")

        raise HTTPException(status_code=500, detail="Prediction failed.")

# =========================
# ログ取得
# =========================
@router.get("/logs")
def get_prediction_logs(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 20,
):
    rows = (
        db.query(PredictionLog)
        .filter(PredictionLog.user_id == current_user.id)
        .order_by(PredictionLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "rci": r.rci,
            "atr": r.atr,
            "vix": r.vix,
            "predicted_volatility": r.predicted_volatility,
            "model_path": r.model_path,
            "status": r.status,
            "error_message": r.error_message,
            "sector": r.sector,
            "time_window": r.time_window,
            "size_category": r.size_category,
            "comment": r.comment,
            "actual_volatility": r.actual_volatility,
            "abs_error": r.abs_error,
        }
        for r in rows
    ]

# =========================
# 再学習（AutoML, カスタム名）
# =========================
@router.post("/retrain")
def retrain_model(
    request_data: dict,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    try:
        model_name = request_data.get("model_name", "vol_model_new.pkl")
        top_k = int(request_data.get("top_k", 3))

        if not model_name.endswith(".pkl"):
            model_name += ".pkl"

        model_path = f"models/{model_name}"

        trainer = AutoTrainer(
            data_path=None,
            model_path=model_path,
            feature_cols=["rci", "atr", "vix"],
            label_col="actual_volatility"
        )
        trainer.load_data_from_db()
        trainer.filter_top_features(top_k=top_k)
        trainer.train_new_model()
        trainer.save_model(model_path)

        return {"message": "モデルを再学習し保存しました", "model_path": model_path}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# =========================
# 実測ボラ登録
# =========================
@router.post("/actual/{log_id}")
def register_actual_volatility(
    log_id: int,
    actual: float,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log = db.query(PredictionLog).filter(
        PredictionLog.id == log_id,
        PredictionLog.user_id == current_user.id
    ).first()

    if not log:
        raise HTTPException(status_code=404, detail="ログが見つかりません。")

    abs_error = abs(actual - log.predicted_volatility) if log.predicted_volatility is not None else None
    log.actual_volatility = actual
    log.abs_error = abs_error
    db.commit()

    return {
        "message": "✅ 実測ボラティリティを登録しました。",
        "actual": actual,
        "abs_error": abs_error
    }

# =========================
# NEW: SHAP再計算＆保存（再学習なし）
# =========================
@router.post("/shap/recompute")
def shap_recompute(
    request_data: dict,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    指定モデルで SHAP を再計算し、models/{basename}_shap_values.pkl と
    models/{basename}_shap_summary.csv を保存して返す
    """
    try:
        model_path = request_data.get("model_path", "models/vol_model.pkl")
        sample_size = int(request_data.get("sample_size", 512))
        feature_cols = request_data.get("feature_cols", ["rci", "atr", "vix"])

        if not os.path.exists(model_path):
            return JSONResponse(status_code=400, content={"error": f"Model not found: {model_path}"})

        # モデル読み込み
        model = joblib.load(model_path)

        # DBから実測付きデータを取得
        trainer = AutoTrainer(
            data_path=None,
            model_path=model_path,
            feature_cols=feature_cols,
            label_col="actual_volatility"
        )
        trainer.load_data_from_db()

        # ← ここが重要：DataFrameの真偽値評価を避ける
        df = getattr(trainer, "data", None)
        if df is None:
            df = getattr(trainer, "df", None)

        if df is None or df.empty:
            return JSONResponse(status_code=400, content={"error": "学習用データがありません（actual_volatility が必要）。"})

        # 特徴量行列
        if not set(feature_cols).issubset(df.columns):
            return JSONResponse(status_code=400, content={"error": f"列が不足しています: {set(feature_cols) - set(df.columns)}"})

        X = df[feature_cols].apply(pd.to_numeric, errors="coerce").dropna()
        if X.empty:
            return JSONResponse(status_code=400, content={"error": "特徴量が空です。"})

        # サンプリング（重さ回避）
        X_use = X.sample(min(len(X), sample_size), random_state=42)

        # SHAP再計算
        explainer = shap.Explainer(model, X_use)
        shap_values = explainer(X_use)

        # 保存先生成
        base = os.path.splitext(model_path)[0]
        shap_values_path = f"{base}_shap_values.pkl"
        summary_csv_path = f"{base}_shap_summary.csv"

        joblib.dump(shap_values, shap_values_path)

        shap_df = pd.DataFrame({
            "feature": X_use.columns,
            "mean_abs_shap": shap_values.abs.mean(0).values
        }).sort_values("mean_abs_shap", ascending=False)
        shap_df.to_csv(summary_csv_path, index=False)

        # 互換: 共通パスにも出力（任意）
        shap_df.to_csv("models/shap_summary.csv", index=False)

        return {
            "message": "SHAPを再計算して保存しました。",
            "model_path": model_path,
            "shap_values_path": shap_values_path,
            "summary_csv_path": summary_csv_path,
            "top_features": shap_df["feature"].head(5).tolist()
        }

    except Exception as e:
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[SHAP Recompute Error]\n{traceback.format_exc()}\n")
        return JSONResponse(status_code=500, content={"error": str(e)})