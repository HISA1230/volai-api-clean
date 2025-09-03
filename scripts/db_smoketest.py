# scripts/db_smoketest.py
# ASCII only. This does not modify data.

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# 1) 環境変数 DATABASE_URL を使います（Neon の接続文字列）
# 例: postgresql://USER:PASSWORD@HOST:5432/DBNAME
url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("Please set DATABASE_URL env var (PostgreSQL connection string).")

engine = create_engine(url, future=True)

# 2) 生クエリで接続チェック
with engine.connect() as conn:
    info = conn.execute(
        text("select current_database() as db, now() as ts")
    ).mappings().one()
    print(f"Connected to DB='{info['db']}' at {info['ts']}")

# 3) ORM テーブルの存在チェック（件数を1つ取得）
with Session(engine) as s:
    n = s.execute(text("select count(*) from model_eval")).scalar_one()
    print("model_eval rows:", n)

print("OK: DB connectivity and table lookup succeeded.")