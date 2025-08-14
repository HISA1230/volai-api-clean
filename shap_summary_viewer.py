# shap_summary_viewer.py

import streamlit as st
import pandas as pd

def main():
    st.title("📊 SHAP重要度ランキング（最新モデル）")

    try:
        df = pd.read_csv("automl/shap_summary.csv")
    except FileNotFoundError:
        st.error("SHAPファイルが見つかりません。まずモデルを再学習してください。")
        return

    st.dataframe(df)

    st.subheader("🔝 上位重要特徴量")
    for _, row in df.head(10).iterrows():
        st.write(f"- **{row['feature']}**: {row['mean_abs_shap']:.6f}（誤差寄与: {row['error_contrib_score']:.2e}）")

if __name__ == "__main__":
    main()