# scripts/peek_train_df.py
import os
import sys
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text

# プロジェクト直下を import パスに追加
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automl.hooks_macro import attach_macro_features

ENGINE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres1234@localhost:5432/volatility_ai",
)
engine = create_engine(ENGINE_URL, future=True)

def to_utc_naive(s: pd.Series) -> pd.Series:
    dt = pd.to_datetime(s, errors="coerce", utc=True)
    return dt.dt.tz_localize(None)

def ensure_date_column(df: pd.DataFrame) -> pd.DataFrame:
    # 既存の date を尊重しつつ、UTC→naive に統一
    if "date" in df.columns:
        df["date"] = to_utc_naive(df["date"])
        return df
    candidates = [
        "logged_at","created_at","ran_at","ts","timestamp","time","datetime",
        "window_start","window_end"
    ]
    for c in candidates:
        if c in df.columns:
            dt = to_utc_naive(df[c])
            if dt.notna().any():
                df["date"] = dt
                return df
    return df

def main():
    with engine.begin() as conn:
        df = pd.read_sql(
            text("SELECT * FROM prediction_logs WHERE actual_volatility IS NOT NULL ORDER BY 1 DESC LIMIT 200"),
            conn
        )
        macro = pd.read_sql(text("SELECT * FROM macro_features ORDER BY date"), conn)

    print("[prediction_logs] shape:", df.shape, "/ cols:", list(df.columns))
    print("[macro_features]  shape:", macro.shape, "/ cols:", list(macro.columns))

    df = ensure_date_column(df)
    if "date" not in df.columns or df["date"].notna().sum() == 0:
        print("⚠️ prediction_logs に date が作れませんでした。候補の日時列名を教えてください。")
        return

    # as-of JOIN（hooks_macro と同条件）
    merged = attach_macro_features(
        df, ENGINE_URL, on_col="date", method="asof", max_lag_days=7
    )

    macro_cols = [c for c in ["vix_m","vix_ma3","vix_ma10","vix_slope3","vix_z20","vix_pr252","oil_ret5","gold_ret5"] if c in merged.columns]
    print("\n[non-null counts for macro columns]")
    if macro_cols:
        print(merged[macro_cols].notna().sum().sort_values(ascending=False))
    else:
        print("（マクロ列が見つかりません）")

    show_cols = [c for c in ["date","rci","atr","vix","vix_m","vix_ma3","vix_z20","oil_ret5","gold_ret5"] if c in merged.columns]
    print("\n[sample rows]")
    if show_cols:
        print(merged[show_cols].head(10).to_string())
    else:
        print("（表示用の列が見つかりません）")

if __name__ == "__main__":
    main()