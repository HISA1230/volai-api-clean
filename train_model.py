# train_model.py

import pandas as pd
import lightgbm as lgb
import joblib
import os

# データ読み込み
try:
    df = pd.read_csv("training_data.csv")
except FileNotFoundError:
    print("❌ training_data.csv が見つかりません。先に export_training_data.py を実行してください。")
    exit()

# 特徴量と目的変数に分離
X = df[["rci", "atr", "vix"]]
y = df["target_volatility"]

# LightGBM モデル定義・学習
model = lgb.LGBMRegressor()
model.fit(X, y)

# モデル保存ディレクトリの確認・作成
os.makedirs("models", exist_ok=True)

# モデル保存
joblib.dump(model, "models/vol_model.pkl")
print("✅ モデルを models/vol_model.pkl に保存しました！")