# --- API core (auth + debug, safe) ---
import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.engine.url import make_url, URL

# DBユーティリティの読み込み（init_db は無い構成でも動くように try/except）
from database.database_user import get_db
try:
    from database.database_user import engine as db_engine  # 推奨: database_user側で生成したengineを使う
except Exception:
    db_engine = None  # engineが無い実装でも起動できるように

try:
    from database.database_user import init_db  # 無い場合はスキップ
except Exception:
    init_db = None

app = FastAPI(title="volai-api-02")

# CORS（必要に応じて許可元を絞ってください）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 例: ["http://localhost:8501", "http://127.0.0.1:8501"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _normalize_driver(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url

def _get_db_url_from_env() -> Optional[str]:
    # SQLALCHEMY_DATABASE_URL を最優先 → 無ければ DATABASE_URL
    url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
    return _normalize_driver(url) if url else None

@app.on_event("startup")
def on_startup():
    # 起動時にテーブル初期化などを行いたい場合だけ database_user.py 側で実装し、ここから呼びます
    if callable(init_db):
        try:
            init_db()
        except Exception as e:
            import logging
            logging.exception("init_db failed: %s", e)

@app.get("/health")
def health():
    return {"ok": True, "signature": "v2030-min", "has_debug": True}

@app.get("/debug/dbinfo")
def debug_dbinfo():
    """
    どのURLで接続しようとしているかを可視化。
    - env_url: 環境変数の生値（ドライバ正規化後）
    - engine_url: 実際にengineが持つURL（パスワードは***でマスク）
    """
    env_url = _get_db_url_from_env()
    engine_url = None

    # engine を安全にマスクして表示
    if db_engine is not None:
        url_str = str(db_engine.url)
        if "://" in url_str and "@" in url_str:
            scheme, rest = url_str.split("://", 1)
            creds, host = rest.split("@", 1)
            if ":" in creds:
                user, _ = creds.split(":", 1)
                creds = f"{user}:***"
            engine_url = f"{scheme}://{creds}@{host}"
        else:
            engine_url = url_str

    # env_url もURLオブジェクトとして安全表示
    safe_env = None
    if env_url:
        try:
            u = make_url(env_url)
            safe_env = str(URL.create(
                drivername=u.drivername,
                username=u.username,
                password="***" if u.password else None,
                host=u.host, port=u.port,
                database=u.database, query=u.query
            ))
        except Exception as e:
            safe_env = f"parse_error: {e}"

    return {"env_url": safe_env, "engine_url": engine_url}

@app.get("/debug/dbping")
def debug_dbping():
    """
    現在のengineでDBに ping します。
    """
    if db_engine is None:
        return {"error": "engine is not initialized (database_user.py must define engine)"}
    try:
        with db_engine.connect() as conn:
            row = conn.execute(text("select current_database() as db, current_user as user")).mappings().first()
            return {"db": row["db"], "user": row["user"]}
    except Exception as e:
        return {"error": f"db connection failed: {e}"}

@app.get("/debug/dbsource")
def debug_dbsource():
    """
    どの環境変数を持っているか・engineの末尾クエリに何が付いているか（channel_bindingが残っていないか）を確認。
    """
    has_sqlalchemy = bool(os.getenv("SQLALCHEMY_DATABASE_URL"))
    has_database = bool(os.getenv("DATABASE_URL"))
    engine_tail = None
    if db_engine is not None:
        s = str(db_engine.url)
        engine_tail = s.split("?", 1)[-1] if "?" in s else ""
    return {
        "has_SQLALCHEMY_DATABASE_URL": has_sqlalchemy,
        "has_DATABASE_URL": has_database,
        "engine_query_tail": engine_tail,  # 例: "sslmode=require"
    }

# --- 認証ルーター（/register, /login, /me） ---
try:
    from routers.user_router import router as auth_router
    app.include_router(auth_router)
except Exception as e:
    # ルーター未実装でもAPI本体は起動するように
    import logging
    logging.warning("auth router not loaded: %s", e)
