# save_model.py
# 正常な状態で vol_model.pkl を再作成するテストスクリプト

import joblib
from sklearn.ensemble import RandomForestRegressor
import numpy as np
import os

# ダミーデータでモデル作成（特徴量3つに固定）
X = np.random.rand(100, 3)  # ← rci, atr, vix を想定
y = np.random.rand(100)

model = RandomForestRegressor()
model.fit(X, y)

# 保存先パス
os.makedirs("models", exist_ok=True)
joblib.dump(model, "models/vol_model.pkl")

print("✅ モデルを正常に保存しました。")