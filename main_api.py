# main_api.py — minimal & robust (drop-in)

from dotenv import load_dotenv
load_dotenv()
# --- add near other imports ---
from sqlalchemy import create_engine, text
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field, EmailStr, confloat

# -----------------------------------------------------------------------------
# App info
# -----------------------------------------------------------------------------
APP_NAME = os.getenv("APP_NAME", "Volatility AI API")
APP_VERSION = os.getenv("APP_VERSION", "2025-08-27-v8")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# CORS
# -----------------------------------------------------------------------------
origins_env = (os.getenv("CORS_ALLOW_ORIGINS") or "*").strip()
allow_origins: List[str] = ["*"] if origins_env in ("", "*") else [
    o.strip() for o in origins_env.split(",") if o.strip()
]

# credentials の可否を環境変数で制御（既定 True）。ただし "*" の場合は False に落とす
_allow_credentials_req = (os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in ("1","true","yes"))
allow_credentials = False if allow_origins == ["*"] else _allow_credentials_req

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Force charset on JSON
# -----------------------------------------------------------------------------
@app.middleware("http")
async def add_utf8_charset(request: Request, call_next):
    response = await call_next(request)
    ct = (response.headers.get("content-type") or "")
    if ct.startswith("application/json") and "charset=" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

# -----------------------------------------------------------------------------
# Exception handlers (JSON で統一して返す)
# -----------------------------------------------------------------------------
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import traceback

# ← 追加：環境変数で trace を出す/出さないを切替
DEBUG_TRACE = os.getenv("API_DEBUG_TRACE", "0").lower() in ("1", "true", "yes")

@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )

@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": exc.detail},
    )

@app.exception_handler(StarletteHTTPException)
async def _starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": exc.detail},
    )

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    content = {
        "error": "internal_error",
        "detail": str(exc),
    }
    # ← 追加：本番では trace を隠し、必要時だけ出す
    if DEBUG_TRACE:
        content["trace"] = traceback.format_exc()[:2000]
    return JSONResponse(status_code=500, content=content)
# -----------------------------------------------------------------------------
# Include predict router (routes_predict.py must exist next to this file)
#   - exposes /predict/... and /api/predict/...
# -----------------------------------------------------------------------------
try:
    from routes_predict import router as pr_router
    app.include_router(pr_router)                 # /predict/...
    app.include_router(pr_router, prefix="/api")  # /api/predict/...
except Exception as e:
    logger.exception("routes_predict load failed: %s", e)
    # ここでは fallback ルートは作らない（下で共通の ping を定義するため）

# -----------------------------------------------------------------------------
# Schemas (Pydantic models)
# -----------------------------------------------------------------------------
class TokenResp(BaseModel):
    access_token: str

class MeResp(BaseModel):
    email: EmailStr
    roles: List[str] = []

class OwnerListResp(BaseModel):
    owners: List[str]
    src: str

class OkResp(BaseModel):
    ok: bool = True

class SettingsLoadResp(BaseModel):
    ok: bool = True
    settings: Dict[str, Any]

class PredictLatestRow(BaseModel):
    ts_utc: str
    time_band: Optional[str] = None
    sector: Optional[str] = None
    size: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)  # 可変デフォルトの安全化
    pred_vol: Optional[confloat(ge=0.0, le=1.0)] = None
    fake_rate: Optional[confloat(ge=0.0, le=1.0)] = None
    confidence: Optional[confloat(ge=0.0, le=1.0)] = None
    price: Optional[float] = Field(None, ge=0.0)
    market_cap: Optional[float] = Field(None, ge=0.0)
    rec_action: Optional[str] = None
    comment: Optional[str] = None

class PingResp(BaseModel):
    ok: bool
    ts: str

class RootResp(BaseModel):
    ok: bool
    name: str
    version: str
    time_utc: str
# -----------------------------------------------------------------------------
# Dev auth stubs (JSON only) so Streamlit login works in local/dev
# -----------------------------------------------------------------------------
class _LoginIn(BaseModel):
    email: str
    password: str

class _MagicIn(BaseModel):
    token: str
    email: Optional[str] = None

@app.post("/login", response_model=TokenResp)
def login(body: _LoginIn):
    # Accept any credentials in dev; return a synthetic bearer token
    return {"access_token": f"dev-{body.email}"}

@app.post("/auth/magic_login", response_model=TokenResp)
def magic_login(body: _MagicIn):
    expected = (os.getenv("AUTOLOGIN_TOKEN") or os.getenv("ADMIN_TOKEN") or "").strip()
    if expected and body.token != expected:
        # explicit JSON 403 (UI expects JSON, not HTML)
        raise HTTPException(status_code=403, detail="invalid magic token")
    email = body.email or os.getenv("API_EMAIL") or "test@example.com"
    return {"access_token": f"dev-{email}"}

@app.get("/me", response_model=MeResp)
def me(Authorization: Optional[str] = Header(default=None)):
    if not Authorization or not Authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    tok = Authorization.split(" ", 1)[1].strip()
    email = tok.replace("dev-", "", 1) if tok.startswith("dev-") else "user@example.com"
    return {"email": email, "roles": ["user"]}

# -----------------------------------------------------------------------------
# Owners stub (UI's safe_owners() will use this if present)
# -----------------------------------------------------------------------------
@app.get("/owners", response_model=OwnerListResp)
def owners():
    return {"owners": ["学也H", "共用", "学也", "正恵", "正恵M"], "src": "static"}

# -----------------------------------------------------------------------------
# Settings save/load stubs (in-memory; good enough for local dev)
# -----------------------------------------------------------------------------
_SETTINGS_MEM: Dict[str, Dict[str, Any]] = {}

class SettingsSaveIn(BaseModel):
    owner: Optional[str] = Field(default=None, max_length=80)
    email: Optional[EmailStr] = None
    settings: Dict[str, Any]

@app.post("/settings/save", response_model=OkResp)
def settings_save(payload: SettingsSaveIn):
    key = f"{payload.email or ''}|{payload.owner or ''}"
    _SETTINGS_MEM[key] = payload.settings
    return {"ok": True}

@app.get("/settings/load", response_model=SettingsLoadResp)
def settings_load(owner: Optional[str] = Query(None), email: Optional[str] = Query(None)):
    key = f"{email or ''}|{owner or ''}"
    return {"ok": True, "settings": _SETTINGS_MEM.get(key, {})}

# -----------------------------------------------------------------------------
# Minimal predict latest stubs (so UI tables render even without DB)
# -----------------------------------------------------------------------------
def _sample_row(ts_dt: datetime, idx: int) -> Dict[str, Any]:
    return {
        "ts_utc": ts_dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "time_band": ["拡張", "プレ", "レギュラーam", "レギュラーpm", "アフター"][idx % 5],
        "sector": ["Tech", "Energy", "Healthcare", "Financials"][idx % 4],
        "size": ["Large", "Mid", "Small", "Penny"][idx % 4],
        "symbols": ["AAPL", "MSFT", "NVDA", "TSLA"][idx % 4: (idx % 4) + 1],
        "pred_vol": 0.012 + 0.005 * (idx % 6),
        "fake_rate": 0.10 + 0.03 * (idx % 5),
        "confidence": 0.40 + 0.08 * (idx % 6),
        "price": 100 + 5 * idx,
        "market_cap": 1_000_000_000 + 50_000_000 * idx,
        "rec_action": "watch",
        "comment": "sample",
    }

@app.get("/api/predict/latest", response_model=List[PredictLatestRow])
@app.get("/predict/latest",     response_model=List[PredictLatestRow])
def predict_latest(n: int = Query(50, ge=1, le=500), mode_live: bool = Query(False)):
    now = datetime.now(timezone.utc)
    k = min(int(n), 50)
    # newer first
    rows = [_sample_row(now - timedelta(minutes=i), i) for i in range(k)]
    return rows

@app.get("/api/predict/ping", response_model=PingResp)
def predict_ping():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

# -----------------------------------------------------------------------------
# Root & health
# -----------------------------------------------------------------------------
@app.get("/", response_model=RootResp)
def root():
    return {
        "ok": True,
        "name": APP_NAME,
        "version": APP_VERSION,
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/health", response_model=OkResp)
def health():

    return {"ok": True}
# --- put near app init or bottom of file ---
_DB_URL = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")

# 先頭のどこか（既にあればOK）
from dotenv import load_dotenv

@app.get("/debug/dbver", response_model=None)  # OkRespの代わりに素直に返す
def debug_dbver():
    # .env を毎回優先的に読む（Windowsの古い永続変数を打ち消す）
    load_dotenv(override=True)

    db_url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    e = create_engine(db_url, pool_pre_ping=True)
    with e.connect() as c:
        ver = c.execute(text("select version()")).scalar()

    return {"ok": True, "version": str(ver)}
# -----------------------------------------------------------------------------
# OpenAPI (no-cache)
# -----------------------------------------------------------------------------
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
        description="API for Volatility AI",
        routes=app.routes,
    )
    schema.setdefault("info", {})["x-openapi-patched"] = "no-cache+dev-auth+predict-latest+owners+settings"
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi

# main_api.py の末尾付近などに一時追加（確認後は削除OK）
from fastapi.routing import APIRoute
for r in app.routes:
    if isinstance(r, APIRoute):
        logger.info("ROUTE %s %s", list(r.methods), r.path)