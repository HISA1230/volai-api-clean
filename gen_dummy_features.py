# gen_dummy_features.py
import os
import shutil
import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)

seed_path = "features/2025-08-01_features.csv"
backup_path = "features/2025-08-01_features.small_backup.csv"

def main():
    if not os.path.exists(seed_path):
        raise FileNotFoundError(f"Seed CSV not found: {seed_path}")

    # 既存の小さなCSVを読み込み（平均・範囲の目安に使う）
    seed = pd.read_csv(seed_path)
    for col in ["rci", "atr", "vix", "volatility"]:
        if col not in seed.columns:
            raise ValueError(f"Missing column in seed CSV: {col}")

    # バックアップ（初回だけ）
    if not os.path.exists(backup_path):
        shutil.copy2(seed_path, backup_path)
        print(f"✅ Backup saved -> {backup_path}")

    # 生成件数
    n = 500

    # 平均と標準偏差（標準偏差が0近い場合のデフォルトを用意）
    def _std(x, default):
        s = float(np.std(x.values))
        return s if s > 1e-9 else default

    rci_mu = float(seed["rci"].mean())
    atr_mu = float(seed["atr"].mean())
    vix_mu = float(seed["vix"].mean())

    rci_sigma = max(_std(seed["rci"], 10.0), 5.0)   # RSIっぽい指標を想定: 0–100
    atr_sigma = max(_std(seed["atr"], 0.05), 0.02)  # ATRは小さめの変動
    vix_sigma = max(_std(seed["vix"], 2.0), 1.0)    # VIXは2〜3程度の分散でもOK

    # ランダム生成（現実的な範囲にクリップ）
    rci = np.clip(rng.normal(rci_mu, rci_sigma, n), 0, 100)
    atr = np.clip(rng.normal(atr_mu, atr_sigma, n), 0.005, None)
    vix = np.clip(rng.normal(vix_mu, vix_sigma, n), 8, 80)

    # 目的変数（volatility）は特徴量に依存＋ノイズ
    # ※モデルが学習できるように、適度な相関を作る
    noise = rng.normal(0, 0.005, n)
    volatility = (
        0.0004 * np.abs(rci - 50) +   # RCIが中立(50)から離れるほどボラ↑
        0.0300 * atr +                # ATRが高いほどボラ↑
        0.0014 * vix +                # VIXが高いほどボラ↑
        noise
    )
    volatility = np.clip(volatility, 0, None)

    df = pd.DataFrame({
        "rci": rci.astype(float),
        "atr": atr.astype(float),
        "vix": vix.astype(float),
        "volatility": volatility.astype(float),
    }).sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    # 元のファイルを上書き（auto_trainer.py のパスを変えずに済む）
    df.to_csv(seed_path, index=False)
    print(f"✅ Generated {len(df):,} rows -> {seed_path}")
    print("   Preview:")
    print(df.head())

if __name__ == "__main__":
    main()