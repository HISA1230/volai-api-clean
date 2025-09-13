from __future__ import annotations
from logging.config import fileConfig
import os, sys, pathlib
from alembic import context
from sqlalchemy import engine_from_config, pool
BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.db import Base  # プロジェクトの Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("SQLALCHEMY_DATABASE_URL") or os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url 未設定（DATABASE_URL か SQLALCHEMY_DATABASE_URL を設定）")
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
    configuration = config.get_section(config.config_ini_section) or {}
    url = configuration.get("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url 未設定（DATABASE_URL か SQLALCHEMY_DATABASE_URL を設定）")
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool, future=True,
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
