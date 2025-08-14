import joblib

model = joblib.load("models/vol_model.pkl")
print("モデルが使用した特徴量一覧：", model.feature_name_)