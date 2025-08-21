# database/database_user.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ローカル既定（PostgreSQL 17 / 5432）
DEFAULT_URL = "postgresql+psycopg2://postgres:postgres1234@localhost:5432/volatility_ai"

# 1) SQLALCHEMY_DATABASE_URL > 2) DATABASE_URL > 3) DEFAULT_URL
url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_URL

# 一部PaaSが "postgres://" を返すので補正
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg2://", 1)

# ローカルはSSLを切る（Neon等クラウドはURL側で sslmode=require を使う運用）
connect_args = {}
if ("localhost" in url) or ("127.0.0.1" in url):
    connect_args["sslmode"] = "disable"

engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()