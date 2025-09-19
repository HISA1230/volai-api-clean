# alembic/env.py  —  minimal & robust (ASCII only)

# --- Ensure import path (MUST be the very first lines) -----------------------
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))           # ...\volatility_ai\alembic
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))    # ...\volatility_ai
PARENT_DIR   = os.path.abspath(os.path.join(PROJECT_ROOT, ".."))  # ...\project

from dotenv import load_dotenv
load_dotenv()  # または override=True にしてもOK

# 1) 一般に必要：親ディレクトリ（C:\project）を sys.path に入れる
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# 2) 念のため：プロジェクト直下（C:\project\volatility_ai）も追加
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# デバッグ表示（必要に応じて消してOK）
print("[env.py] PROJECT_ROOT =", PROJECT_ROOT)
print("[env.py] PARENT_DIR   =", PARENT_DIR)
print("[env.py] sys.path[0:4] =", sys.path[0:4])
# -----------------------------------------------------------------------------

from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config
config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# -----------------------------------------------------------------------------
# Import your models' metadata (robust fallback)
# -----------------------------------------------------------------------------
Base = None

def _try_import():
    # まず正攻法
    try:
        from volatility_ai.models import Base as _Base
        return _Base
    except Exception:
        pass

    # フラット構成のためのフォールバック
    try:
        from models import Base as _Base  # 例: ルート直下に models/ or models.py
        return _Base
    except Exception:
        pass

    try:
        from database.models import Base as _Base  # 例: database/models.py
        return _Base
    except Exception:
        pass

    # ファイル直指定の最終フォールバック
    import importlib.util
    candidates = [
        os.path.join(PROJECT_ROOT, "volatility_ai", "models.py"),
        os.path.join(PROJECT_ROOT, "models.py"),
        os.path.join(PROJECT_ROOT, "database", "models.py"),
        os.path.join(PROJECT_ROOT, "database", "models", "__init__.py"),
    ]
    for path in candidates:
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("models_fallback", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            if hasattr(mod, "Base"):
                return getattr(mod, "Base")
    raise ImportError("Could not locate SQLAlchemy Base. Checked volatility_ai.models, models, database.models, and fallbacks.")

Base = _try_import()
target_metadata = Base.metadata

# -----------------------------------------------------------------------------
# Database URL (env first, then fallback to local sqlite)
# -----------------------------------------------------------------------------
def get_url() -> str:
    return (
        os.getenv("SQLALCHEMY_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "sqlite:///./volai.db"
    )

# -----------------------------------------------------------------------------
# Offline migrations
# -----------------------------------------------------------------------------
def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

# -----------------------------------------------------------------------------
# Online migrations
# -----------------------------------------------------------------------------
def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"url": get_url()},          # ★ ここを "url" にする（prefix="" なので）
        prefix="",                   # prefix="" を使い続ける
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()