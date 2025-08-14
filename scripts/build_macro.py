# scripts/build_macro.py
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from pathlib import Path

# ---- DB 接続情報（必要なら環境に合わせて調整）----
DB_USER = "postgres"
DB_PASS = "postgres1234"
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "volatility_ai"

ENGINE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(ENGINE_URL, future=True)

# ---- ユーティリティ ----
def pct_change(series, n=1):
    return series.pct_change(n)

def zscore(series, win=20, min_periods=10):
    roll = series.rolling(win, min_periods=min_periods)
    return (series - roll.mean()) / roll.std(ddof=0)

def pct_rank(series, win=252, min_periods=60):
    # 過去winの分位（0-1）
    def _rank(x):
        return pd.Series(x).rank(pct=True).iloc[-1]
    return series.rolling(win, min_periods=min_periods).apply(_rank, raw=False)

def slope(series, win=3, min_periods=3):
    # 単純な線形回帰の傾き（標本が少ない場合はNaN）
    def _sl(x):
        idx = np.arange(len(x))
        if len(x) < 2 or np.isnan(x).any():
            return np.nan
        A = np.vstack([idx, np.ones(len(idx))]).T
        m, _ = np.linalg.lstsq(A, x, rcond=None)[0]
        return m
    return series.rolling(win, min_periods=min_periods).apply(_sl, raw=True)

def load_price(symbols):
    q = text("""
        SELECT date, symbol, close
        FROM price_daily
        WHERE symbol = ANY(:syms)
        ORDER BY date
    """)
    with engine.begin() as conn:
        df = pd.read_sql(q, conn, params={"syms": symbols})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df

def pivot_close(df):
    # wide化：index=date, columns=symbol, values=close
    return df.pivot(index="date", columns="symbol", values="close").sort_index()

def main():
    symbols = ["^VIX", "CL=F", "GC=F"]  # 既に取り込み済みの3種
    df = load_price(symbols)
    if df.empty:
        raise SystemExit("price_daily に対象シンボルが見つかりません。")

    wide = pivot_close(df)
    out = pd.DataFrame(index=wide.index)

    # ---- VIX 派生（すぐ効くやつ）----
    vix = wide["^VIX"]
    out["vix"] = vix
    out["vix_ma3"] = vix.rolling(3, min_periods=2).mean()
    out["vix_ma10"] = vix.rolling(10, min_periods=5).mean()
    out["vix_slope3"] = slope(vix, win=3, min_periods=3)
    out["vix_z20"] = zscore(vix, win=20, min_periods=10)
    out["vix_pr252"] = pct_rank(vix, win=252, min_periods=60)

    # ---- 原油・金の5日リターン（方向性を軽く取り込む）----
    if "CL=F" in wide.columns:
        out["oil_ret5"] = pct_change(wide["CL=F"], 5)
    if "GC=F" in wide.columns:
        out["gold_ret5"] = pct_change(wide["GC=F"], 5)

    out = out.reset_index().rename(columns={"index": "date"})
    # 欠損は学習側で扱えるので最小限に留める（必要ならffillも可）
    # out = out.sort_values("date").ffill()

    # ---- DBへ保存（置換）----
    with engine.begin() as conn:
        out.to_sql("macro_features", conn, if_exists="replace", index=False)

    # 進捗
    print("macro_features を作成/更新しました。")
    print(out.tail(5))

if __name__ == "__main__":
    Path("scripts").mkdir(exist_ok=True)
    main()