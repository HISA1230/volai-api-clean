# test_auto_trainer.py

from automl.auto_trainer import AutoTrainer

# インスタンス作成
trainer = AutoTrainer()

# ステップ1〜5（読み込み、分割、訓練、評価、SHAP）
trainer.run_all()

# ステップ6：SHAP上位5特徴量で再学習して比較
trainer.retrain_top_features(top_n=5)