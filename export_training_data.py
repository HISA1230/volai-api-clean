# export_training_data.py

import pandas as pd
from sqlalchemy.orm import Session
from database.database_user import SessionLocal
from models.models_user import PredictionLog

# DBセッション開始
db: Session = SessionLocal()

try:
    # prediction_log テーブルからすべて取得
    logs = db.query(PredictionLog).all()

    # 必要なフィールドを抽出してリストに
    data = [
        {
            "rci": log.rci,
            "atr": log.atr,
            "vix": log.vix,
            "target_volatility": log.predicted_volatility  # ←教師ラベルとして使用
        }
        for log in logs
        if log.status == "success" and log.predicted_volatility is not None
    ]

    # DataFrame化 → CSV保存
    df = pd.DataFrame(data)
    df.to_csv("training_data.csv", index=False)
    print("✅ training_data.csv を正常に出力しました！")

except Exception as e:
    print("❌ エクスポート中にエラー:", str(e))

finally:
    db.close()