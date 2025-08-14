from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.base import Base

# 正しいPostgreSQL接続設定
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:postgres1234@localhost:5432/volatility_ai"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()