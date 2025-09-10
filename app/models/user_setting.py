# app/models/user_setting.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON as JSONGeneric  # fallback
from app.db import Base

# Postgres なら JSONB、その他でも動くようにフォールバック
try:
    JSONType = JSONB
except Exception:
    JSONType = JSONGeneric

class UserSetting(Base):
    __tablename__ = "user_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)

    owner = Column(String, nullable=True)

    notify_enable = Column(Boolean, default=False, nullable=False)
    notify_webhook_url = Column(String, nullable=True)
    notify_title = Column(String, default="VolAI 強シグナル", nullable=False)

    watch_symbols = Column(JSONType, default=list)  # 例: ["7203.T", "AAPL"]

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
