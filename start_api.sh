#!/usr/bin/env bash
set -euo pipefail
set -x

# どの階層で走っているか確認（Renderログに出ます）
pwd
ls -al

python - <<'PY'
import os, urllib.parse as u
from alembic.config import Config
from alembic import command

# DB URL（SQLALCHEMY_DATABASE_URL 優先, 次に DATABASE_URL）
url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
print("DB_URL_PRESENT=", bool(url))
if not url:
    raise SystemExit("No DATABASE_URL/SQLALCHEMY_DATABASE_URL set")

p = u.urlparse(url)
print(f"DB_TARGET={p.scheme}://{p.hostname}:{p.port}")

# Alembic をコードで設定（ini依存を避ける）
cfg = Config()
cfg.set_main_option("script_location", "migrations")
cfg.set_main_option("sqlalchemy.url", url)

print("== Alembic upgrade head ==")
command.upgrade(cfg, "head")
print("== Alembic done ==")
PY

# マイグレーション後に API 起動
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"