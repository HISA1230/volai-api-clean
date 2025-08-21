# models/models_user.py
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Index,
    UniqueConstraint, Boolean, JSON, func
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# =========================
# ユーザー
# =========================
class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    # user_router.py と一致（password_hash）
    password_hash = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    predictions = relationship(
        "PredictionLog",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

# 互換: 旧auth_routerが "User" を参照しても動くように（※クラスの“外”に置く）
User = UserModel

# =========================
# 予測ログ
# =========================
class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 入力特徴量
    rci = Column(Float, nullable=False)
    atr = Column(Float, nullable=False)
    vix = Column(Float, nullable=False)

    # 予測結果（エラー時 None を許容）
    predicted_volatility = Column(Float, nullable=True)

    # 管理系
    model_path = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    error_message = Column(String(512), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # 追加メタ
    sector = Column(String(64), nullable=True)
    time_window = Column(String(64), nullable=True)
    size_category = Column(String(32), nullable=True)
    comment = Column(String(1024), nullable=True)

    # 正解 & 誤差
    actual_volatility = Column(Float, nullable=True)
    abs_error = Column(Float, nullable=True)

    user = relationship("UserModel", back_populates="predictions")

    __table_args__ = (
        Index("ix_prediction_logs_user_id_created_at", "user_id", "created_at"),
    )

# =========================
# モデルのメタ情報（/models で参照）
# =========================
class ModelMeta(Base):
    __tablename__ = "model_meta"

    id = Column(Integer, primary_key=True, index=True)
    model_path = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=True)
    version = Column(String(64), nullable=True)
    owner = Column(String(128), nullable=True)
    description = Column(String(2048), nullable=True)
    tags = Column(JSON, nullable=True)
    pinned = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("model_path", name="uq_model_meta_model_path"),
    )

# =========================
# モデル評価履歴（任意）
# =========================
class ModelEval(Base):
    __tablename__ = "model_eval"

    id = Column(Integer, primary_key=True, index=True)
    model_path = Column(String(255), nullable=False, index=True)
    ran_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    metric_mae = Column(Float, nullable=True)
    n_samples = Column(Integer, nullable=True)
    triggered_by = Column(String(32), nullable=True)
    note = Column(String(1024), nullable=True)
    new_model_path = Column(String(255), nullable=True)
    promoted = Column(Boolean, nullable=False, default=False)