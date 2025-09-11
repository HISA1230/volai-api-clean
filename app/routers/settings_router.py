# app/routers/settings_router.py
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os, traceback

# ====== インポート分離（models と DB を独立に解決） ======
APP_MODELS = None
ROOT_MODELS = None
MODELS_SRC = ""
APP_MODELS_ERR = None
ROOT_MODELS_ERR = None

try:
    import app.models as APP_MODELS  # type: ignore
    MODELS_SRC = "app.models"
except Exception as e:
    APP_MODELS_ERR = repr(e)

if APP_MODELS is None:
    try:
        import models as ROOT_MODELS  # type: ignore
        MODELS_SRC = "models"
    except Exception as e:
        ROOT_MODELS_ERR = repr(e)

# 実際に使う models
models = APP_MODELS or ROOT_MODELS

# DB セッションだけ別トライ
try:
    from app.db import SessionLocal  # type: ignore
    DB_SRC = "app.db"
except Exception:
    from db import SessionLocal  # type: ignore
    DB_SRC = "db"

router = APIRouter(prefix="/settings", tags=["settings"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---- DIAG 切替（環境変数 SETTINGS_DIAG=1/true） ----
DIAG = os.getenv("SETTINGS_DIAG", "0").lower() not in ("0", "false", "no", "off")

if DIAG:
    @router.get("/_diag")
    def _diag():
        mod = models
        return {
            "ok": True,
            "env": {"SETTINGS_DIAG": True},
            "selected_models_src": MODELS_SRC,
            "app_models_file": getattr(APP_MODELS, "__file__", None),
            "root_models_file": getattr(ROOT_MODELS, "__file__", None),
            "selected_models_file": getattr(mod, "__file__", None) if mod else None,
            "has_UserSetting": bool(getattr(mod, "UserSetting", None)) if mod else False,
            "app_models_err": APP_MODELS_ERR,
            "root_models_err": ROOT_MODELS_ERR,
            "db_src": DB_SRC,
        }

# ====== I/O モデル ======
class SaveIn(BaseModel):
    owner: Optional[str] = None
    email: Optional[str] = None
    settings: Dict[str, Any]

# ====== ルータ実装 ======
@router.post("/save")
def save_setting(payload: SaveIn, db: Session = Depends(get_db)):
    Model = getattr(models, "UserSetting", None) if models else None
    if Model is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "UserSetting not resolved",
                "models_src": MODELS_SRC,
                "app_models_file": getattr(APP_MODELS, "__file__", None),
                "root_models_file": getattr(ROOT_MODELS, "__file__", None),
            },
        )
    try:
        row = Model(
            owner=payload.owner or "",
            email=payload.email or "",
            settings=payload.settings,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"ok": True, "id": getattr(row, "id", None), "ts": getattr(row, "created_at", None)}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "type": e.__class__.__name__, "trace": traceback.format_exc()},
        )

@router.get("/load")
def load_setting(owner: Optional[str] = None,
                 email: Optional[str] = None,
                 db: Session = Depends(get_db)):
    Model = getattr(models, "UserSetting", None) if models else None
    if Model is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "UserSetting not resolved",
                "models_src": MODELS_SRC,
                "app_models_file": getattr(APP_MODELS, "__file__", None),
                "root_models_file": getattr(ROOT_MODELS, "__file__", None),
            },
        )
    try:
        q = db.query(Model)
        if owner:
            q = q.filter(Model.owner == owner)
        if email:
            q = q.filter(Model.email == email)
        row = q.order_by(Model.created_at.desc()).first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return {"settings": getattr(row, "settings", {}), "ts": getattr(row, "created_at", None)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "type": e.__class__.__name__, "trace": traceback.format_exc()},
        )