# app/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("SQLALCHEMY_DATABASE_URL")
)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL (or SQLALCHEMY_DATABASE_URL) is not set")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()

# FastAPI 依存で使う DB セッション
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
