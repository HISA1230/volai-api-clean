# retrain_top_features.py

import pandas as pd
import joblib
import os
import lightgbm as lgb
import shap

# ✅ 重要：ここをあなたの SHAP対象ファイルに合わせて調整
data_path = "training_data.csv"

# ✅ 1. データ読込
df = pd.read_csv(data_path)
X = df[["rci", "atr", "vix"]]  # 元の全特徴量
y = df["target_volatility"]

# ✅ 2. 一度モデルを学習して SHAP を計算
model = lgb.LGBMRegressor()
model.fit(X, y)
explainer = shap.Explainer(model)
shap_values = explainer(X)

# ✅ 3. SHAPスコア平均から重要な特徴量を上位3つ取得
shap_df = pd.DataFrame({
    "feature": X.columns,
    "shap_mean": abs(shap_values.values).mean(axis=0)
})
top_features = shap_df.sort_values("shap_mean", ascending=False)["feature"].head(3).tolist()
print("🔍 Top Features:", top_features)

# ✅ 4. 上位特徴量のみで再学習
X_top = X[top_features]
model_top = lgb.LGBMRegressor()
model_top.fit(X_top, y)

# ✅ 5. 保存（新しいファイル名）
os.makedirs("models", exist_ok=True)
model_path = "models/vol_model_top_features.pkl"
joblib.dump((model_top, top_features), model_path)

print(f"✅ モデル再学習完了＆保存: {model_path}")