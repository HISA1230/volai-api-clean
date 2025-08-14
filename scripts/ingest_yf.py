# scripts/ingest_yf.py
# -*- coding: utf-8 -*-
import os
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
import yfinance as yf
from dotenv import load_dotenv

from sqlalchemy import (
    create_engine, MetaData, Table, Column, BigInteger, Integer, String,
    Date, Float, DateTime, UniqueConstraint, text, select, func
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

load_dotenv(override=True)

# ---------- 環境変数 ----------
PGHOST = os.getenv("PGHOST", "localhost")
PGPORT = int(os.getenv("PGPORT", "5432"))
PGUSER = os.getenv("PGUSER", "postgres")
PGPASSWORD = os.getenv("PGPASSWORD", "postgres1234")
PGDATABASE = os.getenv("PGDATABASE", "volatility_ai")

UNIVERSE_RAW = os.getenv("UNIVERSE", "SPY,QQQ,^VIX,CL=F,GC=F")
UNIVERSE = [s.strip() for s in UNIVERSE_RAW.split(",") if s.strip()]

DEFAULT_LOOKBACK_DAYS = int(os.getenv("YF_LOOKBACK_DAYS", "1825"))  # 5年=1825日

DSN = f"postgresql+psycopg2://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{PGDATABASE}"

# ---------- テーブル定義 ----------
metadata = MetaData()

price_daily = Table(
    "price_daily",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("symbol", String(32), nullable=False, index=True),
    Column("date", Date, nullable=False, index=True),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("adj_close", Float),
    Column("volume", BigInteger),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("symbol", "date", name="uq_price_daily_symbol_date"),
)

def ensure_table(engine):
    metadata.create_all(engine)

def _safe_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return float(x)
    except Exception:
        return None

def _safe_int(x) -> Optional[int]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return None

def _last_date_for_symbol(conn, sym: str) -> Optional[date]:
    q = select(func.max(price_daily.c.date)).where(price_daily.c.symbol == sym)
    r = conn.execute(q).scalar()
    return r

def _download_one(sym: str, start_d: date, end_d: date) -> pd.DataFrame:
    # yfinance の end は「その日を含まない」仕様なので +1 日で安全
    end_inclusive = end_d + timedelta(days=1)
    df = yf.download(
        tickers=sym,
        start=start_d.strftime("%Y-%m-%d"),
        end=end_inclusive.strftime("%Y-%m-%d"),
        auto_adjust=False,
        progress=False,
        threads=False,
        interval="1d",
    )
    if isinstance(df.columns, pd.MultiIndex):
        # まれに複数ティッカー形になるのを防衛（単体なら落ちないはず）
        df.columns = [c[0] for c in df.columns]
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    df.index.name = "date"
    return df

def upsert_rows(conn, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    ins = pg_insert(price_daily).values(rows)
    update_cols = {c.name: getattr(ins.excluded, c.name)
                   for c in price_daily.columns
                   if c.name not in ("id", "created_at")}
    stmt = ins.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_=update_cols
    )
    result = conn.execute(stmt)
    return result.rowcount or 0

def ingest(symbols: List[str], lookback_days: int = DEFAULT_LOOKBACK_DAYS):
    engine = create_engine(DSN, future=True)
    ensure_table(engine)

    inserted_total = 0
    updated_total = 0
    per_symbol_stats = []

    with engine.begin() as conn:
        today = date.today()
        default_start = today - timedelta(days=lookback_days)

        for sym in symbols:
            last_d = _last_date_for_symbol(conn, sym)
            start_d = (last_d + timedelta(days=1)) if last_d else default_start
            if start_d > today:
                per_symbol_stats.append({"symbol": sym, "status": "up-to-date", "from": None, "to": None, "rows": 0})
                continue

            df = _download_one(sym, start_d, today)
            if df.empty:
                per_symbol_stats.append({"symbol": sym, "status": "no-data", "from": start_d, "to": today, "rows": 0})
                continue

            df = df.reset_index()
            batch = []
            for _, r in df.iterrows():
                d = r["date"]
                if isinstance(d, pd.Timestamp):
                    d = d.date()
                row = {
                    "symbol": sym,
                    "date": d,
                    "open": _safe_float(r.get("open")),
                    "high": _safe_float(r.get("high")),
                    "low": _safe_float(r.get("low")),
                    "close": _safe_float(r.get("close")),
                    "adj_close": _safe_float(r.get("adj_close")),
                    "volume": _safe_int(r.get("volume")),
                }
                batch.append(row)

            # バッチUPSERT
            affected = 0
            B = 1000
            for i in range(0, len(batch), B):
                affected += upsert_rows(conn, batch[i:i+B])

            per_symbol_stats.append({
                "symbol": sym,
                "status": "ingested",
                "from": start_d,
                "to": today,
                "rows": len(batch),
                "affected": affected,
            })
            inserted_total += len(batch)

    # サマリ出力
    print("=== Ingest Summary ===")
    print(f"DB: {PGDATABASE}  Host: {PGHOST}:{PGPORT}")
    for s in per_symbol_stats:
        print(s)
    print(f"TOTAL rows prepared: {inserted_total}")
    return per_symbol_stats

if __name__ == "__main__":
    print(f"UNIVERSE = {UNIVERSE}")
    stats = ingest(UNIVERSE)