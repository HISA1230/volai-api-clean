# automl/test_shap_analyzer.py

from shap_analyzer import SHAPAnalyzer

if __name__ == "__main__":
    analyzer = SHAPAnalyzer()
    result = analyzer.analyze_shap()
    print(result)
    
    # test_shap_analyzer.py の最後に追記
print("\n📊 SHAP重要度ランキング（上位）")
for i, row in result.iterrows():
    print(f" - {row['feature']}: {row['mean_abs_shap']:.6f}（誤差寄与: {row['error_contrib_score']:.2e}）")