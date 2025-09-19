# main_api.py — minimal, robust, ASCII-only comments
from dotenv import load_dotenv
load_dotenv()

import os
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from sqlalchemy import inspect, text

# ==============================
# DB engine and Base (single source)
# ==============================
try:
    # engine is optional; if this import fails, endpoints that need DB will gracefully 500
    from database.database_user import engine
except Exception:
    engine = None  # type: ignore

try:
    # Base for metadata operations like create_all
    from models.models_user import Base  # type: ignore
except Exception:
    Base = None  # type: ignore

# ==============================
# App info
# ==============================
APP_NAME = os.getenv("APP_NAME", "Volatility AI API")
APP_VERSION = os.getenv("APP_VERSION", "2025-08-27-v8")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
)

# ==============================
# Force charset on JSON
# ==============================
@app.middleware("http")
async def add_utf8_charset(request: Request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset=" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

# ==============================
# /debug guard by ADMIN_TOKEN
# ==============================
class AdminTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/debug"):
            admin = (os.getenv("ADMIN_TOKEN") or "").strip()
            if not admin:
                return JSONResponse(status_code=500, content={"detail": "ADMIN_TOKEN not configured"})
            token = (request.headers.get("X-Admin-Token") or "").strip()
            if token != admin:
                return JSONResponse(status_code=403, content={"detail": "admin token required"})
        return await call_next(request)

app.add_middleware(AdminTokenMiddleware)

# ==============================
# Logging
# ==============================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ==============================
# CORS
# ==============================
origins_env = (os.getenv("CORS_ALLOW_ORIGINS") or "*").strip()
if origins_env in ("", "*"):
    allow_origins: List[str] = ["*"]
else:
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# Routers (optional). If missing, API still boots.
# ==============================
auth_router = models_router = predict_router = scheduler_router = owners_router = None  # type: ignore
_AUTH_ERR = _MODELS_ERR = _PREDICT_ERR = _SCHED_ERR = _OWNERS_ERR = None

try:
    from routers import user_router
    auth_router = user_router.router
    app.include_router(auth_router)
except Exception as e:
    _AUTH_ERR = str(e)
    logger.exception("auth(user) router load failed: %s", e)

try:
    from routers import models_router as _models_router
    models_router = _models_router.router
    app.include_router(models_router)
except Exception as e:
    _MODELS_ERR = str(e)
    logger.exception("models router load failed: %s", e)

try:
    from routers import predict_router as _predict_router
    predict_router = _predict_router.router
    app.include_router(predict_router)
except Exception as e:
    _PREDICT_ERR = str(e)
    logger.exception("predict router load failed: %s", e)

try:
    from routers import scheduler_router as _scheduler_router
    scheduler_router = _scheduler_router.router
    app.include_router(scheduler_router)
except Exception as e:
    _SCHED_ERR = str(e)
    logger.exception("scheduler router load failed: %s", e)

try:
    import routers.owners_router as _owners_router
    owners_router = _owners_router.router
    app.include_router(owners_router)
except Exception as e:
    _OWNERS_ERR = str(e)
    logger.exception("owners router load failed: %s", e)

# ==============================
# Root & health
# ==============================
@app.get("/")
def root():
    return {
        "ok": True,
        "name": APP_NAME,
        "version": APP_VERSION,
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/health")
def health():
    return {"ok": True}

# ==============================
# Minimal stubs when routers are missing
# Only define if predict router failed to load, so we avoid duplicates.
# ==============================
if _PREDICT_ERR is not None or predict_router is None:
    @app.get("/api/predict/ping")
    def predict_ping():
        return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

    @app.get("/api/predict/latest")
    def predict_latest(n: int = 50, mode_live: bool = False):
        # return empty list so UI can render gracefully
        return []

# ==============================
# /debug endpoints (protected by middleware)
# ==============================
@app.get("/debug/ping", summary="Debug Ping (light)")
def debug_ping():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/debug/routes_dump", include_in_schema=False)
def _routes_dump():
    out = []
    for r in app.routes:
        try:
            methods = sorted(list(getattr(r, "methods", [])))
            path = getattr(r, "path", "")
            name = getattr(r, "name", "")
            summary = getattr(getattr(r, "endpoint", None), "summary", None)
            out.append({"path": path, "methods": methods, "name": name, "summary": summary})
        except Exception:
            pass
    return out

@app.get("/debug/dbcheck", summary="Debug Dbcheck")
def debug_dbcheck():
    if engine is None:
        return JSONResponse(status_code=500, content={"ok": False, "error": "engine is None (DB not configured)"})
    try:
        insp = inspect(engine)
        return {
            "ok": True,
            "tables": {
                "users": insp.has_table("users"),
                "prediction_logs": insp.has_table("prediction_logs"),
                "model_meta": insp.has_table("model_meta"),
                "model_eval": insp.has_table("model_eval"),
            },
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.post("/debug/dbcreate", summary="Debug Dbcreate")
def debug_dbcreate():
    if engine is None:
        return JSONResponse(status_code=500, content={"ok": False, "error": "engine is None (DB not configured)"})
    if Base is None:
        return JSONResponse(status_code=500, content={"ok": False, "error": "Base is None (models not loaded)"})
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True, "created": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/debug/dbinfo", summary="Debug Dbinfo")
def debug_dbinfo():
    try:
        if engine is None:
            raise RuntimeError("engine is None")
        return {"ok": True, "url": engine.url.render_as_string(hide_password=True)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/debug/selftest", summary="Debug Selftest")
def debug_selftest():
    out = {"ok": True}

    # Secret key check
    sk = os.getenv("SECRET_KEY")
    out["secret_key_present"] = bool(sk)
    out["secret_key_len"] = len(sk or "")

    # bcrypt / passlib test
    try:
        import bcrypt as _bcrypt  # type: ignore
        import passlib, passlib.context  # type: ignore
        out["bcrypt_version"] = getattr(_bcrypt, "__version__", None) or "unknown"
        out["passlib_version"] = getattr(passlib, "__version__", None)
        ctx = passlib.context.CryptContext(schemes=["bcrypt"], deprecated="auto")
        h = ctx.hash("test1234")
        out["bcrypt_hash_ok"] = bool(h and ctx.verify("test1234", h))
    except Exception as e:
        out["bcrypt_error"] = f"{type(e).__name__}: {e}"
        out["bcrypt_trace"] = traceback.format_exc()
        out["ok"] = False

    # JWT test
    try:
        from jose import jwt  # type: ignore
        token = jwt.encode(
            {"sub": "selftest", "exp": datetime.utcnow() + timedelta(minutes=1)},
            sk or "dummy-secret",
            algorithm="HS256",
        )
        data = jwt.decode(token, sk or "dummy-secret", algorithms=["HS256"])
        out["jwt_ok"] = (data.get("sub") == "selftest")
    except Exception as e:
        out["jwt_error"] = f"{type(e).__name__}: {e}"
        out["jwt_trace"] = traceback.format_exc()
        out["ok"] = False

    # DB connectivity test
    try:
        if engine is None:
            raise RuntimeError("engine is None")
        with engine.connect() as con:
            out["db_select1"] = con.execute(text("SELECT 1")).scalar()
    except Exception as e:
        out["db_error"] = f"{type(e).__name__}: {e}"
        out["db_trace"] = traceback.format_exc()
        out["ok"] = False

    return JSONResponse(out)

# ==============================
# OpenAPI: refresh / no-cache / inject params
# ==============================
@app.post("/ops/openapi/refresh", include_in_schema=False)
@app.get("/ops/openapi/refresh", include_in_schema=False)
def ops_refresh_openapi(request: Request):
    admin = (os.getenv("ADMIN_TOKEN") or "").strip()
    token = (request.headers.get("X-Admin-Token") or "").strip()
    if not admin:
        return JSONResponse(status_code=500, content={"detail": "ADMIN_TOKEN not configured"})
    if token != admin:
        return JSONResponse(status_code=403, content={"detail": "admin token required"})
    app.openapi_schema = None
    return JSONResponse(app.openapi())

@app.post("/debug/openapi/refresh", include_in_schema=False)
@app.get("/debug/openapi/refresh", include_in_schema=False)
def debug_refresh_openapi():
    app.openapi_schema = None
    return JSONResponse(app.openapi())

@app.get("/openapi.json", include_in_schema=False)
def overridden_openapi_json():
    spec = app.openapi()
    return JSONResponse(
        spec,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

def custom_openapi():
    if getattr(app, "openapi_schema", None):
        return app.openapi_schema

    schema = get_openapi(
        title=APP_NAME,
        version=APP_VERSION,
        description="API for volatility AI",
        routes=app.routes,
    )

    # flag to confirm patching
    schema.setdefault("info", {})["x-openapi-patched"] = "logs-summary-params+no-cache+tz_offset-v8"

    # inject params into /predict/logs/summary (if present)
    try:
        path_key = "/predict/logs/summary"
        if path_key in schema.get("paths", {}):
            get_op = schema["paths"][path_key].get("get", {})
            params = get_op.setdefault("parameters", [])
            existing = {p.get("name") for p in params}

            def add_param(name, schema_obj, description):
                if name in existing:
                    return
                params.append({
                    "name": name,
                    "in": "query",
                    "required": False,
                    "schema": schema_obj,
                    "description": description,
                })
                existing.add(name)

            add_param("start", {"type": "string", "format": "date", "title": "Start"}, "YYYY-MM-DD (inclusive)")
            add_param("end", {"type": "string", "format": "date", "title": "End"}, "YYYY-MM-DD (inclusive)")
            add_param("time_start", {"type": "string", "pattern": r"^\d{2}:\d{2}$", "title": "Time Start"}, "HH:MM, e.g. 09:30")
            add_param("time_end", {"type": "string", "pattern": r"^\d{2}:\d{2}$", "title": "Time End"}, "HH:MM, e.g. 15:00")
            add_param("tz_offset", {"type": "integer", "title": "Timezone offset (minutes)", "default": 0},
                      "Local-to-UTC offset in minutes (e.g., JST=540, PDT=-420)")
    except Exception:
        pass

    # auth scheme
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    for path_item in schema.get("paths", {}).values():
        for op in path_item.values():
            if isinstance(op, dict):
                sec = op.get("security") or []
                sec.append({"BearerAuth": []})
                op["security"] = sec

    app.openapi_schema = schema
    return app.openapi_schema

@app.get("/debug/code_fingerprint", include_in_schema=False)
def _code_fingerprint():
    try:
        import routers.predict_router as pr  # type: ignore
        p = pr.__file__
        st = os.stat(p)
        return {
            "predict_router_file": p,
            "mtime": st.st_mtime,
            "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

# attach custom openapi
app.openapi = custom_openapi