# app/models/user_setting.py
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON as JSONGeneric  # fallback for non-Postgres

# Base は app.db から（app 配下/直下 両対応）
try:
    from app.db import Base
except Exception:  # pragma: no cover
    from db import Base  # type: ignore

# Postgres なら JSONB、その他でも動くようにフォールバック
try:
    JSONType = JSONB
except Exception:  # pragma: no cover
    JSONType = JSONGeneric


class UserSetting(Base):
    __tablename__ = "user_settings"

    # Neon の実テーブル: id は text。UUID文字列をデフォルトにして互換にします。
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # DB 側は NULL 可＆非ユニークなので、モデルも合わせます（nullable=True, unique 指定なし）
    email = Column(String, index=True, nullable=True)

    owner = Column(String, nullable=True)

    # ← これが無いと /settings/save が 500 になる
    settings = Column(JSONType, nullable=False)

    # 追加フィールド（任意機能）
    notify_enable = Column(Boolean, default=False, nullable=False)
    notify_webhook_url = Column(String, nullable=True)
    notify_title = Column(String, default="VolAI 強シグナル", nullable=False)

    # 監視銘柄など（JSONB/JSON）
    watch_symbols = Column(JSONType, default=list)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)