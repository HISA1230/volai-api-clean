# app/models/models_volai.py
# ASCII only. SQLAlchemy 2.x style.

from __future__ import annotations
import uuid
from datetime import date, datetime, time
from typing import Optional, Dict, Any, List

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ENUM, UUID, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

# map to enums already created by DDL (create_type=False)
indicator_enum = ENUM('CPI','PPI','CORE_PCE','UNEMPLOYMENT','GDP','FFR',
                      name='indicator_enum', create_type=False, native_enum=True)
model_split_enum = ENUM('train','val','test','live',
                        name='model_split_enum', create_type=False, native_enum=True)
metric_enum = ENUM('MAE','MAPE','RMSE','R2','ACC','F1',
                   name='metric_enum', create_type=False, native_enum=True)
scope_enum = ENUM('symbol','sector','market',
                  name='scope_enum', create_type=False, native_enum=True)

tzts = TIMESTAMP(timezone=True)

class MacroDaily(Base):
    __tablename__ = "macro_daily"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    country: Mapped[str] = mapped_column(sa.String(2), default="US")
    indicator = mapped_column(indicator_enum, index=True)
    period: Mapped[Optional[str]] = mapped_column(sa.String(10))
    value: Mapped[sa.Numeric] = mapped_column(sa.Numeric(18,6))
    release_time_utc: Mapped[Optional[datetime]] = mapped_column(tzts)
    surprise: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    source: Mapped[str] = mapped_column(sa.String(32), default="fmp")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(tzts, server_default=sa.text("now()"))
    updated_at: Mapped[datetime] = mapped_column(tzts, server_default=sa.text("now()"), onupdate=sa.text("now()"))
    __table_args__ = (
        sa.UniqueConstraint("date","country","indicator","period", name="uq_macro_daily_key"),
        sa.Index("ix_macro_indicator_date","indicator","date"),
    )

class MarketIndicator(Base):
    __tablename__ = "market_indicators"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(tzts, index=True)
    key: Mapped[str] = mapped_column(sa.String(40), index=True)
    value: Mapped[sa.Numeric] = mapped_column(sa.Numeric(18,6))
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(tzts, server_default=sa.text("now()"))
    __table_args__ = (
        sa.UniqueConstraint("ts_utc","key", name="uq_market_ts_key"),
        sa.Index("ix_market_key_ts","key","ts_utc"),
    )

class Commodity(Base):
    __tablename__ = "commodities"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(tzts, index=True)
    symbol: Mapped[str] = mapped_column(sa.String(20), index=True)
    price: Mapped[sa.Numeric] = mapped_column(sa.Numeric(18,6))
    unit: Mapped[Optional[str]] = mapped_column(sa.String(16))
    source: Mapped[str] = mapped_column(sa.String(32), default="fmp")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        sa.UniqueConstraint("ts_utc","symbol", name="uq_commod_ts_symbol"),
        sa.Index("ix_commod_symbol_ts","symbol","ts_utc"),
    )

class FxCrypto(Base):
    __tablename__ = "fx_crypto"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(tzts, index=True)
    symbol: Mapped[str] = mapped_column(sa.String(20), index=True)
    price: Mapped[sa.Numeric] = mapped_column(sa.Numeric(18,6))
    corr_7d: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        sa.UniqueConstraint("ts_utc","symbol", name="uq_fx_ts_symbol"),
        sa.Index("ix_fx_symbol_ts","symbol","ts_utc"),
    )

class EventsDay(Base):
    __tablename__ = "events_day"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    region: Mapped[str] = mapped_column(sa.String(8), default="US")
    has_cpi: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    has_fomc: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    earnings_total: Mapped[int] = mapped_column(sa.Integer, default=0)
    earnings_by_sector: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(tzts, server_default=sa.text("now()"))
    updated_at: Mapped[datetime] = mapped_column(tzts, server_default=sa.text("now()"), onupdate=sa.text("now()"))
    __table_args__ = (sa.UniqueConstraint("date","region", name="uq_events_day"),)

class NewsSentiment(Base):
    __tablename__ = "news_sentiment"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(tzts, index=True)
    sector: Mapped[str] = mapped_column(sa.String(40), index=True)
    window_hours: Mapped[int] = mapped_column(sa.SmallInteger, default=6)
    avg_score: Mapped[sa.Numeric] = mapped_column(sa.Numeric(10,6))
    pos_ratio: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(10,6))
    volume: Mapped[int] = mapped_column(sa.Integer, default=0)
    symbols: Mapped[List[str]] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(sa.String(32), default="fmp")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        sa.UniqueConstraint("ts_utc","sector","window_hours", name="uq_news_sector_window_ts"),
        sa.Index("ix_news_sector_ts","sector","ts_utc"),
    )

class SupplyDemand(Base):
    __tablename__ = "supply_demand"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    scope = mapped_column(scope_enum, index=True)
    key: Mapped[str] = mapped_column(sa.String(40), index=True)
    short_interest: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    days_to_cover: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    float_shares: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    pressure_score: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        sa.UniqueConstraint("date","scope","key", name="uq_supply_key"),
        sa.Index("ix_supply_scope_date","scope","date"),
    )

class AnomalyFlag(Base):
    __tablename__ = "anomaly_flags"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(tzts, index=True)
    scope = mapped_column(scope_enum, index=True)
    key: Mapped[str] = mapped_column(sa.String(40), index=True)
    tag: Mapped[str] = mapped_column(sa.String(40), index=True)
    score: Mapped[Optional[sa.Numeric]] = mapped_column(sa.Numeric(18,6))
    level: Mapped[Optional[int]] = mapped_column(sa.SmallInteger)
    details: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        sa.Index("ix_anom_scope_ts","scope","ts_utc"),
        sa.Index("ix_anom_tag_ts","tag","ts_utc"),
    )

class ModelEval(Base):
    __tablename__ = "model_eval"
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4  # app-side UUID generation
    )
    model_name: Mapped[str] = mapped_column(sa.String(64), index=True)
    model_version: Mapped[str] = mapped_column(sa.String(32), index=True)
    sector: Mapped[Optional[str]] = mapped_column(sa.String(40), index=True)
    time_start: Mapped[Optional[time]] = mapped_column(sa.Time)
    time_end: Mapped[Optional[time]] = mapped_column(sa.Time)
    split = mapped_column(model_split_enum)
    metric = mapped_column(metric_enum)
    metric_value: Mapped[sa.Numeric] = mapped_column(sa.Numeric(18,6))
    window_start: Mapped[Optional[date]] = mapped_column(sa.Date)
    window_end: Mapped[Optional[date]] = mapped_column(sa.Date)
    params: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(tzts, server_default=sa.text("now()"))
    __table_args__ = (
        sa.UniqueConstraint("model_name","model_version","sector","time_start","time_end",
                            "split","metric","window_start","window_end", name="uq_model_eval_key"),
        sa.Index("ix_model_eval_model_time","model_name","sector","time_start","time_end"),
    )