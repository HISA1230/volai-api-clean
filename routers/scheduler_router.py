# routers/scheduler_router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import or_
import numpy as np
import os
import logging
import shutil  # ← 昇格でファイルコピーに使用

from auth.auth_jwt import get_current_user
from database.database_user import get_db
from models.models_user import UserModel, PredictionLog, ModelEval, ModelMeta
from automl.auto_trainer import AutoTrainer

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])
log = logging.getLogger(__name__)

# -------- ユーティリティ --------
def compute_mae_for_model(db: Session, model_path: str) -> Dict[str, Any]:
    """PredictionLog から指定モデルの MAE を算出"""
    mp_norm = model_path.replace("\\", "/")
    mp_base = os.path.basename(mp_norm)

    q = (
        db.query(PredictionLog)
        .filter(PredictionLog.actual_volatility.isnot(None))
        .filter(
            or_(
                PredictionLog.model_path == mp_norm,
                PredictionLog.model_path == model_path,
                PredictionLog.model_path == model_path.replace("\\", "/"),
                PredictionLog.model_path.like(f"%/{mp_base}"),
                PredictionLog.model_path.like(f"%\\{mp_base}"),
            )
        )
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
    """models ディレクトリから学習モデルの .pkl を列挙（SHAPは除外）"""
    if not os.path.exists("models"):
        return []
    paths = []
    for f in os.listdir("models"):
        if f.endswith(".pkl") and not f.endswith("_shap_values.pkl"):
            p = os.path.join("models", f)
            paths.append(p.replace("\\", "/"))
    return paths

# -------- リク/レス定義 --------
class RunRequest(BaseModel):
    mae_threshold: Optional[float] = Field(default=None, description="この値を超えるMAEなら再学習")
    min_new_labels: Optional[int] = Field(default=None, description="新規の正解ラベル件数閾値（この数以上なら再学習）")
    top_k: int = 3
    auto_promote: bool = True
    note: Optional[str] = None

class RunResult(BaseModel):
    checked_models: List[Dict[str, Any]]
    triggered: List[Dict[str, Any]]

# -------- 基本エンドポイント（既存のまま） --------
@router.get("/health")
def health_check():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

@router.post("/eval-now")
def eval_now(
    model_path: Optional[str] = None,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """既定（pinned）または指定モデルのMAEを評価"""
    if not model_path:
        pinned = db.query(ModelMeta).filter_by(pinned=True).first()
        if not pinned:
            raise HTTPException(status_code=400, detail="No pinned model")
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
    """MAEが閾値を超えていたらそのモデルを再学習（簡易版）"""
    if not model_path:
        pinned = db.query(ModelMeta).filter_by(pinned=True).first()
        if not pinned:
            raise HTTPException(status_code=400, detail="No pinned model")
        model_path = pinned.model_path

    stat = compute_mae_for_model(db, model_path)
    if stat["mae"] is None:
        return {"error": "No evaluation data"}
    if stat["mae"] <= mae_threshold:
        return {"status": "skipped", "mae": stat["mae"]}

    trainer = AutoTrainer(
        data_path=None,
        model_path=model_path,
        feature_cols=["rci", "atr", "vix"],
        label_col="actual_volatility",
    )
    trainer.load_data_from_db()
    trainer.filter_top_features(top_k=3)
    trainer.train_new_model()
    trainer.save_model(model_path)
    new_stat = compute_mae_for_model(db, model_path)
    return {"status": "retrained", "mae_before": stat["mae"], "mae_after": new_stat["mae"]}

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
    value = [
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
    return {"value": value, "Count": len(value)}  # 互換

@router.post("/run", response_model=RunResult)
def run_scheduler(
    body: RunRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """（既存）JSONボディ必須の総合スケジューラ"""
    models = list_models()
    checked: List[Dict[str, Any]] = []
    triggered: List[Dict[str, Any]] = []

    # 1) 現状MAEを計算
    mae_map: Dict[str, Dict[str, Any]] = {}
    for mp in models:
        stat = compute_mae_for_model(db, mp)
        mae_map[mp] = stat
        checked.append({"model_path": mp, "mae": stat["mae"], "n": stat["n"]})

    # 2) 条件に応じて再学習・昇格
    for mp in models:
        stat = mae_map.get(mp, {"mae": None, "n": 0})
        reason: Optional[str] = None

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
            label_col="actual_volatility",
        )
        trainer.load_data_from_db()

        # 学習データがない場合はスキップ
        if getattr(trainer, "df", None) is None or trainer.df.empty:
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
            log.warning("No training data for %s; skipped retrain.", mp)
            continue

        # 学習〜保存
        trainer.filter_top_features(top_k=max(1, int(body.top_k or 3)))
        trainer.train_new_model()
        trainer.save_model(new_model_path)

        # 自動昇格（簡易）
        promoted = False
        if body.auto_promote:
            try:
                with open("models/.default_model.txt", "w", encoding="utf-8") as f:
                    f.write(new_model_path)
                promoted = True
            except Exception as e:
                log.exception("Failed to promote new model: %s", e)
                promoted = False

        # 履歴へ保存
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

        # ★ 昇格時のSHAP再計算（任意）
        if promoted:
            try:
                from utils.shap_ops import recompute_shap_files
                recompute_shap_files(new_model_path, feature_cols=["rci", "atr", "vix"])
            except Exception as e:
                log.exception("SHAP recompute failed for %s: %s", new_model_path, e)

        triggered.append(
            {
                "base_model": mp,
                "reason": reason,
                "old_mae": stat["mae"],
                "old_n": stat["n"],
                "new_model_path": new_model_path,
                "promoted": promoted,
            }
        )

    # 3) 通知（promoted のときだけ送る）
    if triggered:
        try:
            from utils.notifier import notify_all
            for ev in triggered:
                if not ev.get("promoted"):
                    continue
                title = "📈 モデル再学習イベント"
                payload = {
                    "base_model": ev.get("base_model"),
                    "reason": ev.get("reason"),
                    "old_mae": ev.get("old_mae"),
                    "old_n": ev.get("old_n"),
                    "new_model_path": ev.get("new_model_path"),
                    "promoted": ev.get("promoted"),
                    "note": None,
                }
                notify_all(title, payload)
        except Exception as e:
            log.exception("notify_all failed: %s", e)

    return RunResult(checked_models=checked, triggered=triggered)

# -------- 追加：ボディ不要の簡易3エンドポイント --------

@router.post("/retrain/dryrun")
def retrain_dryrun(
    top_k: int = Query(3, ge=1, le=50, description="相関上位の採用数"),
    current_user: UserModel = Depends(get_current_user),
):
    """ドライラン：データ読み込み→特徴量選別まで（ボディ不要）"""
    trainer = AutoTrainer()
    df = trainer.load_data_from_db()
    feats = trainer.filter_top_features(top_k=top_k)
    return {"rows": len(df), "selected_features": feats, "label": trainer.label_col}

@router.post("/retrain/run")
def retrain_run(
    top_k: int = Query(3, ge=1, le=50, description="相関上位の採用数"),
    model_path: Optional[str] = Query(None, description="保存先モデルパス。未指定なら stage に保存"),
    current_user: UserModel = Depends(get_current_user),
):
    """本番：学習→保存→SHAP出力（ボディ不要）"""
    save_to = model_path or "models/vol_model_stage.pkl"
    trainer = AutoTrainer(model_path=save_to)
    df = trainer.load_data_from_db()
    feats = trainer.filter_top_features(top_k=top_k)
    trainer.train_new_model()
    trainer.save_model(save_to)

    shap_csv = save_to.replace(".pkl", "_shap_summary.csv")
    return {
        "saved_model": save_to,
        "shap_summary": shap_csv,
        "selected_features": feats,
        "rows": len(df),
    }

@router.post("/retrain/promote")
def retrain_promote(
    current_user: UserModel = Depends(get_current_user),
):
    """昇格：stage → 既定モデル（SHAPも同時コピー）"""
    stage = "models/vol_model_stage.pkl"
    dest = "models/vol_model.pkl"
    if not os.path.exists(stage):
        raise HTTPException(status_code=404, detail="staged model not found")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(stage, dest)

    for ext in ["_shap_summary.csv", "_shap_values.pkl"]:
        src = stage.replace(".pkl", ext)
        if os.path.exists(src):
            shutil.copy2(src, dest.replace(".pkl", ext))

    return {
        "default_model": dest,
        "shap_summary": dest.replace(".pkl", "_shap_summary.csv"),
    }