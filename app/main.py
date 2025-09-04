# app/main.py
# -*- coding: utf-8 -*-
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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

# --- CORS ---
origins = (os.getenv("CORS_ALLOW_ORIGINS") or "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"ok": True, "version": "local-dev"}

@app.get("/health")
def health():
    return {"status": "ok"}

# --- static (任意) ---
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except Exception:
    pass

def try_include(module_path: str, attr_name: str = "router") -> bool:
    """module_path から router を import して include_router する小道具"""
    try:
        mod = __import__(module_path, fromlist=[attr_name])
        router = getattr(mod, attr_name)
        app.include_router(router)
        print(f"include ok: {module_path}")
        return True
    except Exception as e:
        logging.getLogger("uvicorn").warning(f"include failed: {module_path} ({e})")
        return False

# app/main.py（ルーター取り込み部分だけ差分）
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

# --- ルーター取り込み（両系統を順に試す） ---
# user
try_include("routers.user_router") or try_include("app.routers.user_router")
# predict
try_include("routers.predict_router") or try_include("app.routers.predict_router")
# strategy
try_include("routers.strategy_router") or try_include("app.routers.strategy_router")
# scheduler
try_include("routers.scheduler_router") or try_include("app.routers.scheduler_router")
# ops-jobs（本番で欲しいやつ）
try_include("routers.ops_jobs_router") or try_include("app.routers.ops_jobs_router")
# どちらの配置でも拾えるように両方トライ（本番はいま app.* を読んでいます）
try_include("app.routers.ops_jobs_router") or try_include("routers.ops_jobs_router")
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
        "host": request.headers.get("host")
    }