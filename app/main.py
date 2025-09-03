# app/main.py
# -*- coding: utf-8 -*-
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import importlib
import inspect
import logging
class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"
# -------- optional import helpers --------
def _import_opt(modname: str):
    """routers.<mod> / app.routers.<mod> の順で存在する方を import。無ければ None。"""
    for base in ("routers", "app.routers"):
        try:
            return importlib.import_module(f"{base}.{modname}")
        except Exception:
            pass
    return None

def _get_router(obj):
    """module から APIRouter を取り出す（属性名 router を想定）。無ければ None。"""
    return getattr(obj, "router", None) if obj else None

# -------- lifespan (起動時にルート一覧をログ出力) --------
@asynccontextmanager
async def lifespan(app: FastAPI):
    lg = logging.getLogger("uvicorn")
    lg.info("=== Lifespan startup: route listing ===")
    for r in app.router.routes:
        methods = ",".join(sorted(getattr(r, "methods", []))) if hasattr(r, "methods") else "-"
        lg.info("ROUTE %-7s %s", methods or "-", getattr(r, "path", str(r)))
    yield

# -------- FastAPI app (single instance) --------
app = FastAPI(
    title="VolAI",
    version="0.1",
    redirect_slashes=True,
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,  # ←これだけ
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/")
def root():
    return {"ok": True, "version": "local-dev"}

@app.get("/health")
def health():
    return {"status": "ok"}

# static
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# -------- detect routers (存在するものだけ) --------
_predict_mod  = _import_opt("predict_router")
_strategy_mod = _import_opt("strategy_router")
_user_mod     = _import_opt("user_router")
_ops_mod      = _import_opt("ops_router")  # 無い環境もある

_predict  = _get_router(_predict_mod)
_strategy = _get_router(_strategy_mod)
_user     = _get_router(_user_mod)
_ops      = _get_router(_ops_mod)

# -------- Router includes（賢いprefix調整）--------
def _smart_include(router, desired_prefix: str = ""):
    rp = (getattr(router, "prefix", "") or "").strip()
    # すでに /api/... を内包 → そのまま
    if rp.startswith("/api/"):
        app.include_router(router)
        return
    # /predict or /strategy を内包 → /api をだけ付与
    if rp in ("/predict", "/strategy"):
        app.include_router(router, prefix="/api")
        return
    # /ops を内包 → そのまま
    if rp == "/ops":
        app.include_router(router)
        return
    # prefix なし → 指定があれば付与
    if rp == "" and desired_prefix:
        app.include_router(router, prefix=desired_prefix)
        return
    # それ以外 → ルーター自身のprefixに従う
    app.include_router(router)

if _ops:      _smart_include(_ops,      desired_prefix="/ops")
if _predict:  _smart_include(_predict,  desired_prefix="/api/predict")
if _strategy: _smart_include(_strategy, desired_prefix="/api/strategy")
if _user:     _smart_include(_user,     desired_prefix="")

# opsユーティリティ（各router内のprefixに任せる）
for name in ("scheduler_router", "metrics_router", "tail_router", "models_router", "owners_router"):
    mod = _import_opt(name)
    rtr = _get_router(mod)
    if rtr:
        app.include_router(rtr)

# ---- メタ系：今どのコードが動いてるか可視化 ----
@app.get("/ops/routes", include_in_schema=False)
def _ops_routes():
    rows = []
    for r in app.router.routes:
        try:
            methods = sorted(list(r.methods)) if hasattr(r, "methods") else []
            rows.append({"path": getattr(r, "path", str(r)), "name": getattr(r, "name", ""), "methods": methods})
        except Exception:
            rows.append({"path": str(r)})
    return JSONResponse(rows)

@app.get("/ops/predict_router_info", include_in_schema=False)
def _predict_router_info():
    mod = _predict_mod
    return {
        "predict_router_prefix": getattr(_predict, "prefix", None) if _predict else None,
        "predict_router_module": getattr(mod, "__file__", None) if mod else None,
        "main_file": __file__,
    }

# なんでもエコー（当たり先の最終確認用）
@app.api_route("/__echo/{full_path:path}", methods=["GET"], include_in_schema=False)
async def __echo(full_path: str, request: Request):
    return {"seen_path": "/" + full_path, "query": dict(request.query_params), "host": request.headers.get("host")}