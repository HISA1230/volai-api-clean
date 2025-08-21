import os
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres1234@localhost:5432/volatility_ai"

url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_URL

# 互換: 一部サービスが "postgres://" を返すことがあるので補正
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg2://", 1)

# ローカルなら sslmode を disable に強制（本番URLはそのまま）
def ensure_local_ssl_disabled(u: str) -> str:
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    is_local = host in ("localhost", "127.0.0.1", "::1")
    if not is_local:
        return u  # 本番などは変更しない

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    # 既に指定があってもローカルは disable を優先
    query["sslmode"] = "disable"
    new_query = urlencode(query)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

url = ensure_local_ssl_disabled(url)

engine = create_engine(url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()