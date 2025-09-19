# scripts/common_db.py
from __future__ import annotations
import os, re
import psycopg2

def _read_env_file(name: str) -> str | None:
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        pass
    return None

def get_db_url() -> str:
    url = os.getenv("DATABASE_URL") or _read_env_file("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set (env or .env)")

    # 防波堤: sqlalchemy 風スキームを psycopg2 用に正規化（1行で両方対応）
    url = re.sub(r"^postgres(?:ql)?\+psycopg2://", "postgresql://", url)
    # ついでに "postgres://" も正式名に統一
    url = re.sub(r"^postgres://", "postgresql://", url)

    # 任意だが安全策: 必要なら接続パラメータを付与
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    if "channel_binding=" not in url:
        url += ("&" if "?" in url else "?") + "channel_binding=require"

    return url

def connect():
    return psycopg2.connect(get_db_url())