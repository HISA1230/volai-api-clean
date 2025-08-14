# automl/shap_analyzer.py

import shap
import pandas as pd
import joblib
import numpy as np

class SHAPAnalyzer:
    def __init__(self, model_path="models/vol_model.pkl", data_path="training_data.csv"):
        self.model_path = model_path
        self.data_path = data_path

    def analyze_shap(self, output_path="automl/shap_summary.csv"):
        # CSV 読み込み
        df = pd.read_csv(self.data_path)
        if 'actual_volatility' not in df.columns or 'predicted_volatility' not in df.columns:
            raise ValueError("CSVに actual_volatility と predicted_volatility の列が必要です")

        # 特徴量と誤差を計算
        feature_cols = [col for col in df.columns if col not in ['actual_volatility', 'predicted_volatility']]
        X = df[feature_cols]
        y_true = df['actual_volatility']
        y_pred = df['predicted_volatility']
        error = np.abs(y_true - y_pred)

        # モデル読込
        model = joblib.load(self.model_path)

        # SHAP値計算
        explainer = shap.Explainer(model.predict, X)
        shap_values = explainer(X)

        # 特徴量ごとのSHAP値平均 × 誤差 で寄与度評価
        mean_shap = np.abs(shap_values.values).mean(axis=0)
        contrib_score = mean_shap * error.mean()

        result_df = pd.DataFrame({
            "feature": feature_cols,
            "mean_abs_shap": mean_shap,
            "error_contrib_score": contrib_score
        }).sort_values("error_contrib_score", ascending=False)

        result_df.to_csv(output_path, index=False)
        print(f"✅ SHAP分析結果を保存しました：{output_path}")
        return result_df