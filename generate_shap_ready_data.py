# generate_shap_ready_data.py

import pandas as pd
import joblib

# モデル読み込み
model = joblib.load("models/vol_model.pkl")

# モデルが使っていた特徴量名を取得（重要！）
used_features = model.feature_name_

# CSV読み込み
df = pd.read_csv("training_data.csv")

# target_volatility → actual_volatility に変換
df.rename(columns={"target_volatility": "actual_volatility"}, inplace=True)

# 予測列が既に存在する場合は削除
if "predicted_volatility" in df.columns:
    df.drop(columns=["predicted_volatility"], inplace=True)

# 型変換（object → float）
for col in used_features:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# モデルと同じ特徴量だけを使う
X = df[used_features]

# 予測
df["predicted_volatility"] = model.predict(X)

# 上書き保存
df.to_csv("training_data.csv", index=False)
print("✅ training_data.csv に actual_volatility を追加して保存しました")