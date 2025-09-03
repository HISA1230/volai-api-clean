# scripts/make_dummy_models.py
# -*- coding: utf-8 -*-
import os
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.dummy import DummyRegressor, DummyClassifier
import joblib

# 既存の特徴量関数を利用
from app.routers.predict_router import build_features

# 学習用の簡易データ（配線テスト用）
def make_training_df(n=600):
    rng = np.random.default_rng(42)
    ts = pd.date_range("2025-08-29", periods=n, freq="h", tz="UTC")
    sector = rng.choice(["Tech","Energy","Health","Finance","Utilities"], size=n)
    symbols = [["AAPL","MSFT"], ["XOM"], ["JNJ"], ["JPM"], ["NEE"]]
    symbols_col = [symbols[i%len(symbols)] for i in range(n)]
    df = pd.DataFrame({
        "ts_utc": ts,
        "sector": sector,
        "avg_score": rng.uniform(0,1,size=n),
        "pos_ratio": rng.uniform(0,1,size=n),
        "volume": rng.normal(100, 30, size=n).clip(1, None),
        "window_h": rng.integers(1,6,size=n),
        "symbols": [",".join(s) for s in symbols_col],
    })
    return df

def main():
    df = make_training_df()
    X, _ = build_features(df)

    base = X.get("avg_score", pd.Series(0.5, index=X.index)).astype(float).to_numpy()
    posr = X.get("pos_ratio", pd.Series(0.5, index=X.index)).astype(float).to_numpy()

    # 回帰: pred_vol を 0-1 に収まる形で
    y_vol = (0.35 + 0.5*(0.6*base + 0.4*posr)).clip(0,1)
    # 分類: fake_rate 用のラベル（低スコアは1=だまし）
    y_fake = (base < 0.5).astype(int)

    vol_pipe = Pipeline([
        ("scaler", StandardScaler(with_mean=False)),
        ("reg", LinearRegression())
    ])
    fake_pipe = Pipeline([
        ("scaler", StandardScaler(with_mean=False)),
        ("clf", LogisticRegression(max_iter=1000))
    ])

    # fit に失敗したらダミーへフォールバック
    try:
        vol_pipe.fit(X, y_vol)
    except Exception:
        vol_pipe = DummyRegressor(strategy="mean").fit(X, y_vol)
    try:
        fake_pipe.fit(X, y_fake)
    except Exception:
        fake_pipe = DummyClassifier(strategy="prior").fit(X, y_fake)

    Path("models").mkdir(exist_ok=True)
    joblib.dump(vol_pipe, "models/vol_model.pkl")
    joblib.dump(fake_pipe, "models/fake_model.pkl")
    print("Saved: models/vol_model.pkl, models/fake_model.pkl")

if __name__ == "__main__":
    main()
