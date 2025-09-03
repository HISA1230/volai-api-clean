# app/etl/jobs.py
from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, Any

from app.database.session import session_scope
from app.etl.upsert import upsert
from app.models.models_volai import MacroDaily, NewsSentiment, SupplyDemand

UTC = timezone.utc


def job_macro_ingest(d1: Optional[date] = None, d2: Optional[date] = None) -> Dict[str, Any]:
    d2 = d2 or date.today()
    d1 = d1 or (d2 - timedelta(days=30))
    rows = [
        dict(date=d2, country="US", indicator="CPI", value=3.2, source="demo", payload={"note": "demo"}),
        dict(date=d2, country="US", indicator="PPI", value=2.1, source="demo", payload={"note": "demo"}),
    ]
    inserted = 0
    with session_scope() as s:
        for r in rows:
            stmt = upsert(
                MacroDaily,
                {
                    "date": r["date"],
                    "country": r.get("country", "US"),
                    "indicator": r["indicator"],
                    "period": "",  # ← None にしない。空文字で統一
                    "value": r["value"],
                    "release_time_utc": None,
                    "surprise": None,
                    "source": r.get("source", "demo"),
                    "payload": r.get("payload", {}),
                },
                key_cols=["date", "country", "indicator", "period"],
                update_cols=["value", "release_time_utc", "surprise", "source", "payload"],
            )
            s.execute(stmt)
            inserted += 1
    return {"job": "macro_ingest", "from": str(d1), "to": str(d2), "rows": inserted}


def job_news_sentiment(window_hours: int = 6) -> Dict[str, Any]:
    now = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
    demo = [
        dict(sector="Tech", avg_score=0.18, pos_ratio=0.62, volume=42, symbols=["AAPL", "MSFT"]),
        dict(sector="Energy", avg_score=-0.05, pos_ratio=0.48, volume=15, symbols=["XOM"]),
    ]
    with session_scope() as s:
        for d in demo:
            stmt = upsert(
                NewsSentiment,
                {
                    "ts_utc": now,
                    "sector": d["sector"],
                    "window_hours": window_hours,
                    "avg_score": d["avg_score"],
                    "pos_ratio": d["pos_ratio"],
                    "volume": d["volume"],
                    "symbols": d["symbols"],
                    "source": "demo",
                    "meta": {},
                },
                key_cols=["ts_utc", "sector", "window_hours"],
                update_cols=["avg_score", "pos_ratio", "volume", "symbols", "source", "meta"],
            )
            s.execute(stmt)
    return {"job": "news_sentiment", "ts_utc": now.isoformat(), "sectors": len(demo)}


def job_supply_demand(target_date: Optional[date] = None) -> Dict[str, Any]:
    d = target_date or date.today()
    demo = [
        dict(scope="sector", key="Tech", short_interest=12.3, days_to_cover=2.1, float_shares=1.2e9),
        dict(scope="sector", key="Energy", short_interest=8.7, days_to_cover=1.4, float_shares=6.0e8),
    ]

    def pressure(si, dtc):
        if si is None or dtc is None:
            return None
        return float(si) * float(dtc)

    with session_scope() as s:
        for r in demo:
            stmt = upsert(
                SupplyDemand,
                {
                    "date": d,
                    "scope": r["scope"],
                    "key": r["key"],
                    "short_interest": r["short_interest"],
                    "days_to_cover": r["days_to_cover"],
                    "float_shares": r["float_shares"],
                    "pressure_score": pressure(r["short_interest"], r["days_to_cover"]),
                    "meta": {},
                },
                key_cols=["date", "scope", "key"],
                update_cols=["short_interest", "days_to_cover", "float_shares", "pressure_score", "meta"],
            )
            s.execute(stmt)
    return {"job": "supply_demand", "date": str(d), "groups": len(demo)}