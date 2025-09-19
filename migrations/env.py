# migrations/env.py
from __future__ import annotations

import os
import sys
import pathlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ============ import path を通す ============
# .../migrations の 1つ上（= リポジトリルート）を sys.path に追加
BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ============ Base の import（app/直下 両対応） ============
try:
    from app.db import Base  # type: ignore
except Exception:
    from db import Base  # type: ignore

# ============ Alembic 基本設定 & ログ ============
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# このセクション名（通常 "alembic"）
SECTION = config.config_ini_section

# ============ DB URL を環境変数から注入 ============
# Render/本番: SQLALCHEMY_DATABASE_URL（推奨）→ なければ DATABASE_URL
db_url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
if db_url:
    # ini 内の sqlalchemy.url を上書き
    config.set_section_option(SECTION, "sqlalchemy.url", db_url)

# オートジェネレートが参照するメタデータ
target_metadata = Base.metadata


def _require_url() -> str:
    """現在の設定から sqlalchemy.url を取り出し、無ければ明確にエラー。"""
    # set_section_option で入れた値は get_section_option / get_section から読める
    url = (
        config.get_section_option(SECTION, "sqlalchemy.url")
        or config.get_main_option("sqlalchemy.url")
        or ""
    )
    if not url:
        raise RuntimeError(
            "alembic: sqlalchemy.url が未設定です。"
            "環境変数 SQLALCHEMY_DATABASE_URL か DATABASE_URL を設定してください。"
            "（Neon 直結の形式: postgresql+psycopg2://...:5432/neondb?sslmode=require）"
        )
    return url


def run_migrations_offline() -> None:
    """オフライン（Engine を生成しない）モード。"""
    url = _require_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """オンライン（Engine を生成して接続）モード。"""
    # 上で注入した URL を含むセクション辞書を取得
    configuration = config.get_section(SECTION) or {}
    url = configuration.get("sqlalchemy.url") or ""
    if not url:
        # 念のため二重チェック
        url = _require_url()
        config.set_section_option(SECTION, "sqlalchemy.url", url)

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # サーバレス/外部DBに優しい
        future=True,
    )

    with connectable.connect() as connection:
        is_sqlite = connection.engine.url.get_backend_name() == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()