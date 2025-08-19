# --- API core (auth + debug + BearerAuth in OpenAPI) ---
import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from sqlalchemy.engine.url import make_url, URL

# DB: engine は database_user.py 側で生成されたものを使う
try:
    from database.database_user import engine as db_engine
except Exception:
    db_engine = None

# ルーター（認証）
try:
    from routers.user_router import router as auth_router
except Exception as e:
    auth_router = None

app = FastAPI(
    title="volai-api-02",
    version="2030",
    description="High-Accuracy Volatility Prediction API (FastAPI + PostgreSQL + AutoML)",
)

# CORS（必要に応じて絞ってください）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 例: ["http://localhost:8502", "http://127.0.0.1:8502"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 環境変数から接続URL（表示用） ---
def _normalize_driver(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url

def _get_db_url_from_env() -> Optional[str]:
    url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
    return _normalize_driver(url) if url else None

# --- ヘルスチェック ---
@app.get("/health")
def health():
    return {"ok": True, "signature": "v2030-min", "has_debug": True}

# --- デバッグ: 接続URLの可視化 ---
@app.get("/debug/dbinfo")
def debug_dbinfo():
    env_url = _get_db_url_from_env()
    safe_env = None
    if env_url:
        try:
            u = make_url(env_url)
            safe_env = str(
                URL.create(
                    drivername=u.drivername,
                    username=u.username,
                    password="***" if u.password else None,
                    host=u.host,
                    port=u.port,
                    database=u.database,
                    query=u.query,
                )
            )
        except Exception as e:
            safe_env = f"parse_error: {e}"

    engine_url = None
    if db_engine is not None:
        s = str(db_engine.url)
        if "://" in s and "@" in s:
            scheme, rest = s.split("://", 1)
            creds, host = rest.split("@", 1)
            if ":" in creds:
                user, _ = creds.split(":", 1)
                creds = f"{user}:***"
            engine_url = f"{scheme}://{creds}@{host}"
        else:
            engine_url = s

    return {"env_url": safe_env, "engine_url": engine_url}

# --- デバッグ: DBへ ping ---
@app.get("/debug/dbping")
def debug_dbping():
    if db_engine is None:
        return {"error": "engine is not initialized (database_user.py must define engine)"}
    try:
        with db_engine.connect() as conn:
            row = (
                conn.execute(text("select current_database() as db, current_user as user"))
                .mappings()
                .first()
            )
            return {"db": row["db"], "user": row["user"]}
    except Exception as e:
        return {"error": f"db connection failed: {e}"}

# --- （任意）デバッグ: どの変数があるか ---
@app.get("/debug/dbsource")
def debug_dbsource():
    has_sqlalchemy = bool(os.getenv("SQLALCHEMY_DATABASE_URL"))
    has_database = bool(os.getenv("DATABASE_URL"))
    tail = ""
    if db_engine is not None:
        s = str(db_engine.url)
        tail = s.split("?", 1)[-1] if "?" in s else ""
    return {
        "has_SQLALCHEMY_DATABASE_URL": has_sqlalchemy,
        "has_DATABASE_URL": has_database,
        "engine_query_tail": tail,  # 例: "sslmode=require"
    }

# --- 認証ルーターを登録 ---
if auth_router:
    app.include_router(auth_router)

# --- OpenAPI に Bearer 認証を追加（Authorize ボタンを出す） ---
EXCLUDE_SECURITY_PATHS = {
    "/",
    "/health",
    "/debug/dbinfo",
    "/debug/dbping",
    "/debug/dbsource",
    "/login",
    "/register",
}

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    comps = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    comps["BearerAuth"] = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}

    # すべてのパスに Bearer を要求（ただし EXCLUDE_SECURITY_PATHS は除外）
    for path, ops in openapi_schema.get("paths", {}).items():
        for _, operation in ops.items():
            if path in EXCLUDE_SECURITY_PATHS:
                operation.pop("security", None)
            else:
                operation["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
