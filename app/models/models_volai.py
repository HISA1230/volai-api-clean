from __future__ import annotations
from datetime import date, datetime
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, ENUM

class Base(DeclarativeBase):
    pass

indicator_enum = ENUM(name="indicator_enum", create_type=False)
scope_enum = ENUM(name="scope_enum", create_type=False)

class MacroDaily(Base):
    __tablename__ = "macro_daily"
    date: Mapped[date] = mapped_column(sa.Date, primary_key=True)
    country: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    indicator = mapped_column(indicator_enum, primary_key=True)
    period: Mapped[str | None] = mapped_column(sa.Text, primary_key=True, nullable=True)
    value: Mapped[float | None] = mapped_column(sa.Numeric(18, 6))
    release_time_utc: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    surprise: Mapped[float | None] = mapped_column(sa.Numeric(18, 6))
    source: Mapped[str | None] = mapped_column(sa.Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)

class NewsSentiment(Base):
    __tablename__ = "news_sentiment"
    ts_utc: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)
    sector: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    window_hours: Mapped[int] = mapped_column(sa.SmallInteger, primary_key=True)
    avg_score: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    pos_ratio: Mapped[float | None] = mapped_column(sa.Numeric(9, 6))
    volume: Mapped[int | None] = mapped_column(sa.Integer)
    symbols: Mapped[list | dict | None] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(sa.Text)
    meta: Mapped[dict | None] = mapped_column(JSONB, default=dict)

class SupplyDemand(Base):
    __tablename__ = "supply_demand"
    date: Mapped[date] = mapped_column(sa.Date, primary_key=True)
    scope = mapped_column(scope_enum, primary_key=True)
    key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    short_interest: Mapped[float | None] = mapped_column(sa.Numeric(18, 6))
    days_to_cover: Mapped[float | None] = mapped_column(sa.Numeric(18, 6))
    float_shares: Mapped[float | None] = mapped_column(sa.Numeric(18, 6))
    pressure_score: Mapped[float | None] = mapped_column(sa.Numeric(18, 6))
    meta: Mapped[dict | None] = mapped_column(JSONB, default=dict)
