# utils/predictor.py

import joblib
import pandas as pd

# モデルの読み込み（最初に1回だけ）
model = joblib.load("models/vol_model.pkl")  # ← モデルファイルパスに合わせて修正

def predict_volatility(input_data: dict):
    """
    入力: dict（例: {"rci": 0.8, "atr": 0.03, "vix": 17.5, ...}）
    出力: float（予測ボラティリティ）
    """
    df = pd.DataFrame([input_data])
    pred = model.predict(df)[0]
    return float(pred)