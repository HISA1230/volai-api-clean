import os
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.models_user import Base  # User/テーブル定義を読み込む

_ENGINE = None
_SessionLocal = None

def _normalize_driver(url: str) -> str:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url

def _get_db_url() -> Optional[str]:
    url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
    return _normalize_driver(url) if url else None

def get_engine():
    global _ENGINE
    if _ENGINE is None:
        url = _get_db_url()
        _ENGINE = create_engine(url, pool_pre_ping=True, pool_recycle=300) if url else None
    return _ENGINE

def get_sessionmaker():
    global _SessionLocal
    if _SessionLocal is None:
        eng = get_engine()
        _SessionLocal = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    return _SessionLocal

def get_db():
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    eng = get_engine()
    if eng is None:
        return
    Base.metadata.create_all(bind=eng)
