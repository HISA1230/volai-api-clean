# scripts/label_fill.py
import os
import math
import pandas as pd
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text

# 環境変数 DATABASE_URL があれば優先
DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres1234@localhost:5432/volatility_ai")
engine = create_engine(DB_URL, future=True)

SYMBOL = "SPY"  # 必要なら '^VIX' などに変更可

def safe_print(msg: str):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        # 出力先が CP932 等で絵文字不可でも落ちないように
        print(msg.encode("ascii", "ignore").decode("ascii"), flush=True)

def load_prices():
    q = text("SELECT date, symbol, close FROM price_daily WHERE symbol = :sym ORDER BY date")
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"sym": SYMBOL}, parse_dates=["date"])
    if df.empty:
        raise RuntimeError(f"price_daily に {SYMBOL} がありません。")
    df = df.sort_values("date").reset_index(drop=True)
    df["ret_abs"] = (df["close"] / df["close"].shift(1)).apply(lambda x: abs(math.log(x)) if pd.notna(x) and x > 0 else None)
    return df

def update_labels():
    # 昨日までを対象
    today = datetime.now(timezone.utc).date()
    yday  = today - timedelta(days=1)

    prices = load_prices()
    price_by_date = prices.set_index("date")

    # prediction_logs で actual_volatility が NULL のもの（昨日まで）
    q_pending = text("""
        SELECT id, predicted_volatility, created_at::date AS d
        FROM prediction_logs
        WHERE actual_volatility IS NULL
          AND created_at::date <= :yday
        ORDER BY created_at
    """)
    with engine.connect() as conn:
        pend = pd.read_sql(q_pending, conn, params={"yday": yday})
    if pend.empty:
        print("🔎 埋める対象なし（すべて充填済み）")
        return

    # 各 d について、d と d+1 の終値から実現ボラ（絶対リターン）を計算
    filled = 0
    with engine.begin() as conn:
        for d in sorted(pend["d"].unique()):
            d1 = d + timedelta(days=1)
            if d not in price_by_date.index or d1 not in price_by_date.index:
                # 価格が欠けていればスキップ
                continue
            vol = price_by_date.loc[d1, "ret_abs"]
            if pd.isna(vol):
                continue

            # 当日（d）に作られた行を一括更新
            upd = text("""
                UPDATE prediction_logs
                SET actual_volatility = :vol,
                    abs_error = CASE
                        WHEN predicted_volatility IS NOT NULL
                        THEN ABS(predicted_volatility - :vol)
                        ELSE NULL
                    END
                WHERE created_at::date = :d AND actual_volatility IS NULL
            """)
            conn.execute(upd, {"vol": float(vol), "d": d})
            filled += 1

    safe_print(f"✅ ラベル充填完了：{filled} 日分更新（対象日 <= {yday}）")

if __name__ == "__main__":
    update_labels()