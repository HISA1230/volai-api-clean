# app/main.py
# -*- coding: utf-8 -*-
import logging
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

# ===== import を両対応にする（app.配下 / 直下のどちらでも動く） =====
# 必須: magic_login
try:
    from app.routers.magic_login import router as magic_login_router
except Exception:
    from routers.magic_login import router as magic_login_router  # type: ignore

# 任意: owners（無ければスキップ）
try:
    from app.routers.owners import router as owners_router
except Exception:
    try:
        from routers.owners import router as owners_router  # type: ignore
    except Exception:
        owners_router = None

# db / models（先に一度だけ import。以後はこの SessionLocal/engine を使い回し）
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

# --- ルータ登録（必須系） ---
app.include_router(magic_login_router)
if owners_router:
    app.include_router(owners_router)

# === settings（固定 import／必要なら fallback 付に変更可）===
try:
    from app.routers.settings_router import router as settings_router
except Exception:
    from routers.settings_router import router as settings_router  # type: ignore
app.include_router(settings_router)

# --- 起動時：DBテーブル作成 + OWNERS_LIST シード ---
@app.on_event("startup")
def _startup_db_seed():
    Base.metadata.create_all(bind=engine)
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
if origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # "*" と併用不可
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

# --- 追加ルータの取り込みユーティリティ ---
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

def include_once(prefix: str, candidates: list[str]) -> None:
    """prefix で始まる既存ルートがあれば二重登録しない。無ければ候補から最初に成功した1つだけを登録。"""
    for r in app.router.routes:
        p = getattr(r, "path", "")
        if isinstance(p, str) and p.startswith(prefix):
            return
    for mod in candidates:
        if try_include(mod):
            return

# --- 他ルータ（通常） ---
# auto_router（/auto 配下）は router 側で prefix="/auto" を付ける運用
for mod in ("app.routers.auto_router", "routers.auto_router"):
    if try_include(mod): break
for mod in ("app.routers.user_router", "routers.user_router"):
    if try_include(mod): break
for mod in ("app.routers.predict_router", "routers.predict_router"):
    if try_include(mod): break
for mod in ("app.routers.strategy_router", "routers.strategy_router"):
    if try_include(mod): break
for mod in ("app.routers.scheduler_router", "routers.scheduler_router"):
    if try_include(mod): break

# db_router は片方でOK
try_include("app.routers.db_router") or try_include("routers.db_router")

# ops/jobs は重複防止で include_once
include_once("/ops/jobs", ["app.routers.ops_jobs_router", "routers.ops_jobs_router"])

# （settings はすでに固定 import 済みなので include_once しない）

# === ops/dbinfo（import 成功に依らず常に出す） ===
from sqlalchemy import text  # 上で import 済みなら重複OK（無害）
try:
    from app.db import SessionLocal
except Exception:
    from db import SessionLocal  # type: ignore

@app.get("/ops/dbinfo", include_in_schema=False)
def ops_dbinfo():
    try:
        with SessionLocal() as db:
            bind = db.get_bind()
            url = bind.url.render_as_string(hide_password=True)
            row = db.execute(text("select current_database(), current_user")).fetchone()
            return {"ok": True, "url": url, "db": row[0], "user": row[1]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

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

@app.get("/ops/version", include_in_schema=False)
def _version():
    marker = ""
    try:
        marker = pathlib.Path("app/_build_id.txt").read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return {
        "app": "volai-api",
        "git": os.getenv("RENDER_GIT_COMMIT", "")[:7],
        "build": os.getenv("RENDER_BUILD_ID", ""),
        "marker": marker,
    }
    
@app.get("/ops/dbenv", include_in_schema=False)
def _dbenv():
    import os, urllib.parse as u
    rows = {}
    for k in ("SQLALCHEMY_DATABASE_URL","DATABASE_URL"):
        s = os.getenv(k, "")
        p = u.urlparse(s)
        rows[k] = {
            "present": bool(s),
            "scheme": p.scheme,
            "host": p.hostname,
            "port": p.port,
            "path": p.path,
            "has_space_in_pw": (" " in (p.password or "")),
        }
    return rows    

# === 追加: owners の診断と再シード ===
from sqlalchemy import select  # 既に import 済みなら重複OK

@app.get("/ops/owners_diag", include_in_schema=False)
def owners_diag():
    try:
        owners_env = os.getenv("OWNERS_LIST", "")
        env_list = [s.strip() for s in owners_env.split(",") if s.strip()]
        with SessionLocal() as db:
            rows = db.execute(select(models.Owner.name).order_by(models.Owner.name)).scalars().all()
        return {"ok": True, "env": env_list, "table": rows}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

@app.post("/ops/owners_seed", include_in_schema=False)
def owners_seed():
    owners_env = os.getenv("OWNERS_LIST", "")
    names = [s.strip() for s in owners_env.split(",") if s.strip()]
    added = []
    with SessionLocal() as db:
        for n in names:
            if not db.query(models.Owner).filter_by(name=n).first():
                db.add(models.Owner(name=n))
                added.append(n)
        db.commit()
    return {"ok": True, "added": added}