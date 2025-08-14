# utils/shap_ops.py
import os, pickle, pandas as pd
from typing import Dict, List, Optional
from pathlib import Path

import shap  # pip install shap が必要（既に入っていればOK）
from automl.auto_trainer import AutoTrainer

def recompute_shap_files(
    model_path: str,
    feature_cols: Optional[List[str]] = None,
    sample_n: int = 2000
) -> Dict[str, str]:
    """
    新モデルに対して SHAP を再計算し、models/ 配下に
    *_shap_values.pkl と *_shap_summary.csv を出力する
    """
    model_path = model_path.replace("\\", "/")
    base = Path(model_path).with_suffix("").name
    out_values = f"models/{base}_shap_values.pkl"
    out_summary = f"models/{base}_shap_summary.csv"

    # 学習データの読み出し（DBから）
    trainer = AutoTrainer(
        data_path=None,
        model_path=model_path,
        feature_cols=feature_cols or ["rci", "atr", "vix"],
        label_col="actual_volatility"
    )
    trainer.load_data_from_db()
    if trainer.df is None or trainer.df.empty:
        raise RuntimeError("No training data to compute SHAP")

    X = trainer.df[trainer.feature_cols].copy()
    if len(X) > sample_n:
        X = X.sample(sample_n, random_state=42).reset_index(drop=True)

    # モデル読み込み
    with open(model_path, "rb") as f:
        model = pickle.load(f)

    # SHAP 計算（木モデル前提）
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    # 保存：値（pkl）とサマリ（csv）
    Path("models").mkdir(exist_ok=True)
    pd.to_pickle({"X": X, "values": shap_values, "features": trainer.feature_cols}, out_values)

    # mean|SHAP| を算出
    import numpy as np
    mean_abs = np.mean(np.abs(shap_values), axis=0)
    summary = pd.DataFrame({"feature": trainer.feature_cols, "mean_abs_shap": mean_abs})
    summary.sort_values("mean_abs_shap", ascending=False, inplace=True)
    summary.to_csv(out_summary, index=False)

    return {"shap_values_path": out_values, "summary_csv_path": out_summary, "top_features": summary.head(3)["feature"].tolist()}