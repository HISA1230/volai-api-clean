# volatility_ai/models.py
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, DateTime, Float, JSON, Integer
from datetime import datetime, timezone

Base = declarative_base()

class Log(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    owner: Mapped[str | None] = mapped_column(String(80), index=True)
    time_band: Mapped[str | None] = mapped_column(String(40), index=True)
    sector: Mapped[str | None] = mapped_column(String(40), index=True)
    size: Mapped[str | None] = mapped_column(String(20), index=True)
    symbol: Mapped[str | None] = mapped_column(String(20), index=True)
    symbols: Mapped[dict | list | None] = mapped_column(JSON)
    pred_vol: Mapped[float | None] = mapped_column(Float)
    fake_rate: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    rec_action: Mapped[str | None] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(String(400))

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    roles: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))