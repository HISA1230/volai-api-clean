# app/main.py
# -*- coding: utf-8 -*-
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ルータ & DB の import は app. プレフィックスで統一
from app.routers.magic_login import router as magic_login_router
from app.routers.owners import router as owners_router
from app.db import engine, Base, SessionLocal
from app import models


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    lg = logging.getLogger("uvicorn")
    lg.info("=== startup: route listing ===")
    for r in app.router.routes:
        methods = ",".join(sorted(getattr(r, "methods", []))) if hasattr(r, "methods") else "-"
        lg.info("ROUTE %-7s %s", methods or "-", getattr(r, "path", str(r)))
    yield


app = FastAPI(
    title="Volatility AI API",
    version="0.1",
    redirect_slashes=True,
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

# --- ルータ（まず固定のもの） ---
app.include_router(magic_login_router)
app.include_router(owners_router)


# --- 起動時：DBテーブル作成 + OWNERS_LIST シード ---
@app.on_event("startup")
def _startup_db_seed():
    # ① テーブル作成（存在しなければ作成）
    Base.metadata.create_all(bind=engine)

    # ② OWNERS_LIST をシード（例: "学也,学也H,正恵,正恵M,共用"）
    owners_env = os.getenv("OWNERS_LIST", "")
    names = [s.strip() for s in owners_env.split(",") if s.strip()]
    if names:
        with SessionLocal() as db:
            for n in names:
                if not db.query(models.Owner).filter_by(name=n).first():
                    db.add(models.Owner(name=n))
            db.commit()


# --- CORS ---
origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
origins = [o.strip() for o in origins_raw.split(",") if o.strip()]

# NOTE: allow_credentials=True と allow_origins=["*"] は併用不可。
# "*" の場合は credentials を False にし、明示ドメインなら True にする。
if origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --- Health & Root（重複ナシ：GET+HEAD の単一定義） ---
@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"ok": True, "version": "prod"}


# --- static (任意) ---
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except Exception:
    # static ディレクトリが無い環境では無視
    pass


# --- ルーター取り込みユーティリティ（可変構成のため残す） ---
def try_include(module_path: str, attr_name: str = "router") -> bool:
    try:
        mod = __import__(module_path, fromlist=[attr_name])
        router = getattr(mod, attr_name)
        app.include_router(router)
        print(f"include ok: {module_path}")
        return True
    except Exception as e:
        logging.getLogger("uvicorn").warning(f"include failed: {module_path} ({e})")
        return False


# --- 追加ルーター取り込み（両系統を順に試すが、重複 include はしない） ---
for mod in ("routers.user_router", "app.routers.user_router"):
    if try_include(mod):
        break
for mod in ("app.routers.predict_router", "routers.predict_router"):
    if try_include(mod):
        break
for mod in ("routers.strategy_router", "app.routers.strategy_router"):
    if try_include(mod):
        break
for mod in ("routers.scheduler_router", "app.routers.scheduler_router"):
    if try_include(mod):
        break
for mod in ("routers.ops_jobs_router", "app.routers.ops_jobs_router"):
    if try_include(mod):
        break

# db（新規）
try_include("routers.db_router") or try_include("app.routers.db_router")


# --- 運用補助 ---
@app.get("/ops/routes", include_in_schema=False)
def _ops_routes():
    rows = []
    for r in app.router.routes:
        try:
            methods = sorted(list(r.methods)) if hasattr(r, "methods") else []
            rows.append(
                {
                    "path": getattr(r, "path", str(r)),
                    "name": getattr(r, "name", ""),
                    "methods": methods,
                }
            )
        except Exception:
            rows.append({"path": str(r)})
    return rows


@app.api_route("/__echo/{full_path:path}", methods=["GET"], include_in_schema=False)
async def __echo(full_path: str, request: Request):
    return {
        "seen_path": "/" + full_path,
        "query": dict(request.query_params),
        "host": request.headers.get("host"),
    }
