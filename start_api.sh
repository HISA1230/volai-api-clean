#!/usr/bin/env bash
set -euo pipefail
set -x

echo "PWD: $(pwd)"
ls -al

# DB URL を確認
DB_URL="${SQLALCHEMY_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ -z "$DB_URL" ]]; then
  echo "ERROR: DATABASE_URL/SQLALCHEMY_DATABASE_URL not set" >&2
  exit 1
fi
echo "DB_URL_PRESENT=true"

echo "== Alembic upgrade head =="
# alembic.ini がリポジトリのルートにある前提
alembic -c alembic.ini upgrade head
echo "== Alembic done =="

# FastAPI を起動
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
