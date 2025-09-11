# models.py
from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models import User, PredictionLog, Owner, UserSetting
__all__ = ["User", "PredictionLog", "Owner", "UserSetting"]

from db import Base

# 既存: Owner（SQLAlchemy 2.0 の型付き宣言）
class Owner(Base):
    __tablename__ = "owners"
    id:   Mapped[int]  = mapped_column(primary_key=True)
    name: Mapped[str]  = mapped_column(String(100), unique=True, index=True)

# 追加: UI 設定を保存するテーブル
class UserSetting(Base):
    __tablename__ = "user_settings"
    id        = Column(Integer, primary_key=True, index=True)
    owner     = Column(String(64),  index=True, nullable=True)    # 画面のオーナー選択
    email     = Column(String(255), index=True, nullable=True)    # ログインユーザー（任意）
    settings  = Column(JSON, nullable=False)                      # UI設定（JSON）
    created_at = Column(DateTime(timezone=True), server_default=func.now())