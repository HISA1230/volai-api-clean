# database/database_user.py
import os
from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 1) まず SQLALCHEMY_DATABASE_URL を見る。無ければ DATABASE_URL を使う
def _pick_url() -> Optional[str]:
    return os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")

# 2) postgres:// → postgresql+psycopg2:// に正規化
def _normalize_driver(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url

# 3) `channel_binding` を外し、`sslmode=require` を保証
def _sanitize_query(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.pop("channel_binding", None)          # ← これで常に外す
    if q.get("sslmode") is None:
        q["sslmode"] = "require"
    new_query = urlencode(q, doseq=True)
    return urlunparse(p._replace(query=new_query))

_DB_URL = _sanitize_query(_normalize_driver(_pick_url()))
if not _DB_URL:
    raise RuntimeError("No DATABASE_URL / SQLALCHEMY_DATABASE_URL set")

# main_api.py が import して使う engine / get_db を提供
engine = create_engine(_DB_URL, pool_pre_ping=True, pool_recycle=300, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
