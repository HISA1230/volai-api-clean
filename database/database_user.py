# database/database_user.py
import os
from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def _pick_url() -> Optional[str]:
    # ← ここを2択に絞る：まず SQLALCHEMY_DATABASE_URL、無ければ DATABASE_URL
    return os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")

def _normalize_driver(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    # postgres:// → postgresql+psycopg2:// に正規化
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

def _sanitize_query(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    # ← ここがポイント：channel_binding は常に外す
    q.pop("channel_binding", None)
    # sslmode は require を保証
    if q.get("sslmode") is None:
        q["sslmode"] = "require"
    new_query = urlencode(q, doseq=True)
    return urlunparse(p._replace(query=new_query))

_DB_URL = _sanitize_query(_normalize_driver(_pick_url()))
if not _DB_URL:
    raise RuntimeError("No DATABASE_URL / SQLALCHEMY_DATABASE_URL set")

# main_api.py が import して使う公開オブジェクト
engine = create_engine(_DB_URL, pool_pre_ping=True, pool_recycle=300, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
