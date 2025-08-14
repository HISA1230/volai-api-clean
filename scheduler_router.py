from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import os, numpy as np

from auth.auth_jwt import get_current_user
from database.database_user import get_db
from models.models_user import UserModel, PredictionLog, ModelEval, ModelMeta
from automl.auto_trainer import AutoTrainer

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])

# -------- ユーティリティ --------
def compute_mae_for_model(db: Session, model_path: str) -> Dict[str, Any]:
    q = (
        db.query(PredictionLog)
        .filter(PredictionLog.model_path == model_path)
        .filter(PredictionLog.actual_volatility.isnot(None))
    )
    rows = q.all()
    if not rows:
        return {"mae": None, "n": 0}
    abs_errors = []
    for r in rows:
        if r.abs_error is not None:
            abs_errors.append(r.abs_error)
        elif r.predicted_volatility is not None and r.actual_volatility is not None:
            abs_errors.append(abs(r.predicted_volatility - r.actual_volatility))
    if not abs_errors:
        return {"mae": None, "n": 0}
    return {"mae": float(np.mean(abs_errors)), "n": len(abs_errors)}

def list_models() -> List[str]:
    if not os.path.exists("models"):
        return []
    return [
        os.path.join("models", f)
        for f in os.listdir("models")
        if f.endswith(".pkl") and not f.endswith("_shap_values.pkl")
    ]

# -------- 共通レスポンス --------
class RunRequest(BaseModel):
    mae_threshold: Optional[float] = Field(default=None, description="この値を超えるMAEなら再学習")
    min_new_labels: Optional[int] = Field(default=None, description="新規の正解ラベル件数閾値（この数以上なら再学習）")
    top_k: int = 3
    auto_promote: bool = True
    note: Optional[str] = None

class RunResult(BaseModel):
    checked_models: List[Dict[str, Any]]
    triggered: List[Dict[str, Any]]

# -------- 基本エンドポイント --------
@router.get("/health")
def health_check():
    """疎通確認"""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

@router.post("/eval-now")
def eval_now(
    model_path: Optional[str] = None,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """既定または指定モデルのMAEを評価"""
    if not model_path:
        pinned = db.query(ModelMeta).filter_by(pinned=True).first()
        if not pinned:
            return {"error": "No pinned model"}
        model_path = pinned.model_path
    stat = compute_mae_for_model(db, model_path)
    return {"model_path": model_path, "mae": stat["mae"], "n": stat["n"]}

@router.post("/retrain-if-needed")
def retrain_if_needed(
    model_path: Optional[str] = None,
    mae_threshold: float = 0.05,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """MAEが閾値を超えていたら再学習"""
    if not model_path:
        pinned = db.query(ModelMeta).filter_by(pinned=True).first()
        if not pinned:
            return {"error": "No pinned model"}
        model_path = pinned.model_path
    stat = compute_mae_for_model(db, model_path)
    if stat["mae"] is None:
        return {"error": "No evaluation data"}
    if stat["mae"] <= mae_threshold:
        return {"status": "skipped", "mae": stat["mae"]}

    # 再学習
    trainer = AutoTrainer(
        data_path=None,
        model_path=model_path,
        feature_cols=["rci", "atr", "vix"],
        label_col="actual_volatility"
    )
    trainer.load_data_from_db()
    trainer.filter_top_features(top_k=3)
    trainer.train_new_model()
    trainer.save_model(model_path)
    new_stat = compute_mae_for_model(db, model_path)
    return {"status": "retrained", "mae_before": stat["mae"], "mae_after": new_stat["mae"]}

# -------- 拡張スケジューラー --------
@router.get("/status")
def status(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recs = (
        db.query(ModelEval)
        .order_by(ModelEval.ran_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "ran_at": r.ran_at.isoformat(),
            "model_path": r.model_path,
            "metric_mae": r.metric_mae,
            "n_samples": r.n_samples,
            "triggered_by": r.triggered_by,
            "new_model_path": r.new_model_path,
            "promoted": r.promoted,
            "note": r.note,
        }
        for r in recs
    ]

@router.post("/run", response_model=RunResult)
def run_scheduler(
    body: RunRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    models = list_models()
    checked = []
    triggered = []

    # 1) 現状MAE計算
    mae_map = {}
    for mp in models:
        stat = compute_mae_for_model(db, mp)
        mae_map[mp] = stat
        checked.append({"model_path": mp, "mae": stat["mae"], "n": stat["n"]})

    # 2) 判定と再学習
    for mp in models:
        stat = mae_map.get(mp, {"mae": None, "n": 0})
        reason = None
        if body.mae_threshold is not None and stat["mae"] is not None and stat["mae"] > body.mae_threshold:
            reason = "threshold"
        elif body.min_new_labels is not None and stat["n"] is not None and stat["n"] >= body.min_new_labels:
            reason = "count"
        if reason is None:
            continue

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = os.path.splitext(os.path.basename(mp))[0]
        new_model_path = f"models/{base}_auto_{stamp}.pkl"

        trainer = AutoTrainer(
            data_path=None,
            model_path=new_model_path,
            feature_cols=["rci", "atr", "vix"],
            label_col="actual_volatility"
        )
        trainer.load_data_from_db()
        if trainer.df is None or trainer.df.empty:
            eval_rec = ModelEval(
                model_path=mp,
                metric_mae=stat["mae"],
                n_samples=stat["n"],
                triggered_by=reason,
                note="no training data",
                new_model_path=None,
                promoted=False,
            )
            db.add(eval_rec)
            db.commit()
            continue

        trainer.filter_top_features(top_k=body.top_k)
        trainer.train_new_model()
        trainer.save_model(new_model_path)

        promoted = False
        if body.auto_promote:
            try:
                with open("models/.default_model.txt", "w", encoding="utf-8") as f:
                    f.write(new_model_path)
                promoted = True
            except Exception:
                promoted = False

        eval_rec = ModelEval(
            model_path=mp,
            metric_mae=stat["mae"],
            n_samples=stat["n"],
            triggered_by=reason,
            note=body.note,
            new_model_path=new_model_path,
            promoted=promoted,
        )
        db.add(eval_rec)
        db.commit()

        triggered.append({
            "base_model": mp,
            "reason": reason,
            "old_mae": stat["mae"],
            "old_n": stat["n"],
            "new_model_path": new_model_path,
            "promoted": promoted,
        })

    return RunResult(checked_models=checked, triggered=triggered)