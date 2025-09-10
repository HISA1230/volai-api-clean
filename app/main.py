# app/main.py
# -*- coding: utf-8 -*-
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ===== import を両対応にする（app.配下 / 直下のどちらでも動く） =====
# routers.magic_login
try:
    from app.routers.magic_login import router as magic_login_router
except Exception:
    from routers.magic_login import router as magic_login_router  # type: ignore

# routers.owners（無ければスキップ可能）
try:
    from app.routers.owners import router as owners_router
except Exception:
    try:
        from routers.owners import router as owners_router  # type: ignore
    except Exception:
        owners_router = None  # ルータ無しでも起動できるように

# db / models
try:
    from app.db import engine, Base, SessionLocal
    from app import models
except Exception:
    from db import engine, Base, SessionLocal  # type: ignore
    import models  # type: ignore


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

# --- ルータ登録（必須系）
app.include_router(magic_login_router)
# 任意系（存在すれば）
if owners_router:
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
# "*" と credentials の両立不可 → 自動で安全側に
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

# --- Health & Root ---
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
    pass

# --- 追加ルータの動的取り込み（どちらの配置でもOKに） ---
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

for mod in ("routers.user_router", "app.routers.user_router"):
    if try_include(mod): break
for mod in ("app.routers.predict_router", "routers.predict_router"):
    if try_include(mod): break
for mod in ("routers.strategy_router", "app.routers.strategy_router"):
    if try_include(mod): break
for mod in ("routers.scheduler_router", "app.routers.scheduler_router"):
    if try_include(mod): break
for mod in ("routers.ops_jobs_router", "app.routers.ops_jobs_router"):
    if try_include(mod): break

# db（新規）
try_include("routers.db_router") or try_include("app.routers.db_router")

for mod in ("routers.settings_router", "app.routers.settings_router"):
    if try_include(mod): break
    
# === settings_router 直インクルード（保険） ===
def _has_settings_routes() -> bool:
    try:
        for r in app.router.routes:
            p = getattr(r, "path", "")
            if isinstance(p, str) and p.startswith("/settings"):
                return True
    except Exception:
        pass
    return False

if not _has_settings_routes():
    try:
        from app.routers.settings_router import router as _settings_router_direct
    except Exception:
        try:
            from routers.settings_router import router as _settings_router_direct  # type: ignore
        except Exception:
            _settings_router_direct = None

    if _settings_router_direct:
        app.include_router(_settings_router_direct)
        print("include ok: settings_router (direct fallback)")
            
# --- 運用補助 ---
@app.get("/ops/routes", include_in_schema=False)
def _ops_routes():
    rows = []
    for r in app.router.routes:
        try:
            methods = sorted(list(r.methods)) if hasattr(r, "methods") else []
            rows.append({
                "path": getattr(r, "path", str(r)),
                "name": getattr(r, "name", ""),
                "methods": methods
            })
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
import os

@app.get("/ops/version", include_in_schema=False)
def _version():
    return {
        "app": "volai-api",
        "git": os.getenv("RENDER_GIT_COMMIT", "")[:8],
        "build": os.getenv("RENDER_BUILD_ID", ""),
    }