# retrain_model.py

from automl.auto_trainer import AutoTrainer

if __name__ == "__main__":
    trainer = AutoTrainer(
        data_path=None,  # DBから読み込むのでNone
        model_path="models/vol_model_top_features.pkl",
        feature_cols=["rci", "atr", "vix"],  # 初期の全候補
        label_col="actual_volatility"
    )

    trainer.load_data_from_db()

    # データが1件以下の場合の処理
    if trainer.df is None or len(trainer.df) <= 1:
        print("⚠️ 学習に必要なデータ件数が不足しています（最低2件必要）")
    else:
        trainer.filter_top_features(top_k=3)
        trainer.train()
        trainer.save_model("models/vol_model_top_features.pkl")