# main_api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

# ルーターは1回だけインポート＆登録（重複させない）
from routers import user_router, models_router, predict_router, scheduler_router, debug_router

app = FastAPI(title="Volatility AI API", version="1.0.0", docs_url="/docs", redoc_url="/redoc")

# --- CORS（開発時はワイルドカード。必要に応じて本番は絞る） ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番は ["https://your-ui.example.com"] 等に制限
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ルーター登録（順不同） ---
app.include_router(user_router.router)
app.include_router(models_router.router)
app.include_router(predict_router.router)
app.include_router(scheduler_router.router)
app.include_router(debug_router.router)  # ← 追加した Debug ルーター

# --- ヘルスチェック ---
@app.get("/health")
def health():
    return {"ok": True}

# --- ルーター読込チェック（簡易） ---
@app.get("/debug/routers")
def routers_loaded():
    def has_prefix(prefix: str) -> bool:
        try:
            return any(getattr(r, "path", "").startswith(prefix) for r in app.routes)
        except Exception:
            return False

    result = {
        "auth_loaded": (has_prefix("/login") and has_prefix("/register") and has_prefix("/me")),
        "models_loaded": has_prefix("/models"),
        "predict_loaded": has_prefix("/predict"),
        "scheduler_loaded": has_prefix("/scheduler"),
        "debug_loaded": has_prefix("/debug"),
    }
    return result

# --- Swagger/Authorize で Bearer を出すための軽い schema 追加（任意） ---
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description="Volatility AI FastAPI backend",
        routes=app.routes,
    )
    # Bearer スキームの追記
    comps = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    comps["HTTPBearer"] = {"type": "http", "scheme": "bearer"}

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi