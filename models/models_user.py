# models/models_user.py
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Index,
    UniqueConstraint, Boolean, JSON, func, Text
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

    # ★ここが重要：routers/user_router.py が参照するのは password_hash
    # かつ bcrypt ハッシュは 60文字以上になるので Text にしておく
    password_hash = Column(Text, nullable=False)

    # どちらでも動きますがサーバ側で付与できる server_default を採用
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    predictions = relationship(
        "PredictionLog",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


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
# モデルのメタ情報（A-29）
# =========================
class ModelMeta(Base):
    __tablename__ = "model_meta"

    id = Column(Integer, primary_key=True, index=True)

    # 例: "models/vol_model.pkl"（一意）
    model_path = Column(String(255), nullable=False, unique=True, index=True)

    display_name = Column(String(255), nullable=True)     # 表示名
    version = Column(String(64), nullable=True)           # バージョン
    owner = Column(String(128), nullable=True)            # オーナー
    description = Column(String(2048), nullable=True)     # 説明/メモ
    tags = Column(JSON, nullable=True)                    # 例: ["prod", "lgbm"]

    pinned = Column(Boolean, nullable=False, default=False)  # 一覧で上位表示

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("model_path", name="uq_model_meta_model_path"),
    )


# =========================
# A-30: モデル評価履歴
# =========================
class ModelEval(Base):
    __tablename__ = "model_eval"

    id = Column(Integer, primary_key=True, index=True)
    model_path = Column(String(255), nullable=False, index=True)  # 対象モデル
    ran_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    metric_mae = Column(Float, nullable=True)        # 実行後のMAE
    n_samples = Column(Integer, nullable=True)       # 評価に使った件数
    triggered_by = Column(String(32), nullable=True) # "threshold", "count", "manual" など
    note = Column(String(1024), nullable=True)       # 備考
    new_model_path = Column(String(255), nullable=True)   # 再学習で保存した新モデル（なければNone）
    promoted = Column(Boolean, nullable=False, default=False)  # 既定モデル昇格したか


# =========================
# （参考）Pydantic リクエストモデル
#   ※ 既に別ファイルにあるなら重複不要。ここに置いてもOK。
# =========================
from pydantic import BaseModel as PydBaseModel

class UserCreate(PydBaseModel):
    email: str
    password: str

class UserLogin(PydBaseModel):
    email: str
    password: str