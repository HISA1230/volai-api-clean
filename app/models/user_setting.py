# app/models/user_setting.py
import uuid
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON as JSONGeneric  # fallback
from sqlalchemy.sql import func
from app.db import Base

# Postgres なら JSONB、その他DBでも動くようフォールバック
try:
    JSONType = JSONB
except Exception:
    JSONType = JSONGeneric

class UserSetting(Base):
    __tablename__ = "user_settings"

    # Neon 側は id=text なので String + UUID文字列
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # どちらも任意（owner+email の最新を読み出す想定）
    email = Column(String, index=True, nullable=True)
    owner = Column(String, nullable=True)

    # これが無いと /settings/save でエラーになります
    settings = Column(JSONType, nullable=False)

    # 通知系（任意）
    notify_enable = Column(Boolean, default=False, nullable=False)
    notify_webhook_url = Column(String, nullable=True)
    notify_title = Column(String, default="VolAI 強シグナル", nullable=False)

    # ウォッチ銘柄
    watch_symbols = Column(JSONType, default=list)

    # 生成/更新（DB側で自動）
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)