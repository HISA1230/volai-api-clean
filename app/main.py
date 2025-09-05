# app/main.py
# -*- coding: utf-8 -*-
import os, logging
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

# --- HEAD も許可する /health と / のみ定義（重複禁止） ---
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

# --- ルーター取り込みユーティリティ（1回だけ定義） ---
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

# --- ルーター取り込み（両系統を順に試すが、重複 include はしない） ---
for mod in ("routers.user_router", "app.routers.user_router"):
    if try_include(mod): break
for mod in ("routers.predict_router", "app.routers.predict_router"):
    if try_include(mod): break
for mod in ("routers.strategy_router", "app.routers.strategy_router"):
    if try_include(mod): break
for mod in ("routers.scheduler_router", "app.routers.scheduler_router"):
    if try_include(mod): break
for mod in ("routers.ops_jobs_router", "app.routers.ops_jobs_router"):
    if try_include(mod): break

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