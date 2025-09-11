# app/routers/settings_router.py
from __future__ import annotations

import os
import inspect
from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text, desc

# =====================================
# 設定
# =====================================
DIAG = os.getenv("SETTINGS_DIAG", "0").lower() not in ("0", "false", "no", "off", "")

router = APIRouter(prefix="/settings", tags=["settings"])

# =====================================
# DB: app.db / db 両対応
# =====================================
def _import_db():
    try:
        from app.db import SessionLocal  # type: ignore
        return SessionLocal, "app.db"
    except Exception:
        from db import SessionLocal  # type: ignore
        return SessionLocal, "db"

SessionLocal, _DB_SRC = _import_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =====================================
# models: app.models / models 両対応（UserSetting を解決）
# =====================================
def _get_module_file(mod) -> Optional[str]:
    try:
        return inspect.getfile(mod)  # type: ignore
    except Exception:
        return None

def _import_models() -> Tuple[Any, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    return:
      models_module, selected_src, app_models_file, root_models_file, app_models_err, root_models_err
    """
    app_err = root_err = None
    app_file = root_file = None

    # 1) app.models 優先
    try:
        import app.models as app_models  # type: ignore
        app_file = _get_module_file(app_models)
        if getattr(app_models, "UserSetting", None) is not None:
            return app_models, "app.models", app_file, None, None, None
        app_err = "app.models.UserSetting is None"
    except Exception as e:
        app_err = repr(e)

    # 2) ルート models（ブリッジ）
    try:
        import models as root_models  # type: ignore
        root_file = _get_module_file(root_models)
        if getattr(root_models, "UserSetting", None) is not None:
            return root_models, "models", None, root_file, app_err, None
        root_err = "models.UserSetting is None"
    except Exception as e:
        root_err = repr(e)

    # 3) どちらも解決できない
    return None, "(unresolved)", app_file, root_file, app_err, root_err

_MODELS, _MODELS_SRC, _APP_MODELS_FILE, _ROOT_MODELS_FILE, _APP_MODELS_ERR, _ROOT_MODELS_ERR = _import_models()

# =====================================
# スキーマ
# =====================================
class SaveIn(BaseModel):
    owner: Optional[str] = None
    email: Optional[str] = None
    settings: Dict[str, Any]

# =====================================
# 診断（常時登録：DIAG=0 でも叩ける）
# =====================================
@router.get("/_diag")
def _diag():
    return {
        "ok": True,
        "env": {"SETTINGS_DIAG": DIAG, "RAW": os.getenv("SETTINGS_DIAG", None)},
        "selected_models_src": _MODELS_SRC,
        "app_models_file": _APP_MODELS_FILE,
        "root_models_file": _ROOT_MODELS_FILE,
        "selected_models_file": _APP_MODELS_FILE if _MODELS_SRC == "app.models" else _ROOT_MODELS_FILE,
        "has_UserSetting": bool(getattr(_MODELS, "UserSetting", None)),
        "app_models_err": _APP_MODELS_ERR,
        "root_models_err": _ROOT_MODELS_ERR,
        "db_src": _DB_SRC,
    }

# =====================================
# _peek（常時登録。DIAG=0 のときは 404）
# =====================================
@router.get("/_peek")
def _peek(
    owner: Optional[str] = None,
    email: Optional[str] = None,
    n: int = Query(5, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if not DIAG:
        raise HTTPException(status_code=404, detail="not found")

    try:
        conds = []
        params: Dict[str, Any] = {"n": n}
        if owner:
            conds.append("owner = :owner")
            params["owner"] = owner
        if email:
            conds.append("email = :email")
            params["email"] = email
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        sql = f"""
            SELECT id, owner, email, settings, created_at, updated_at
            FROM user_settings
            {where}
            ORDER BY id DESC
            LIMIT :n
        """
        rows = db.execute(text(sql), params).mappings().all()
        return {"count": len(rows), "items": rows}
    except Exception as e:
        if DIAG:
            raise HTTPException(status_code=500, detail={"error": "peek_failed", "msg": str(e)})
        raise HTTPException(status_code=500, detail="internal error")

# =====================================
# 保存
# =====================================
@router.post("/save")
def save_setting(payload: SaveIn, db: Session = Depends(get_db)):
    Model = getattr(_MODELS, "UserSetting", None)
    if Model is None:
        detail = {
            "error": "UserSetting not resolved",
            "models_src": _MODELS_SRC,
            "app_models_file": _APP_MODELS_FILE,
            "root_models_file": _ROOT_MODELS_FILE,
        }
        raise HTTPException(status_code=500, detail=detail)

    try:
        row = Model(  # type: ignore[call-arg]
            owner=(payload.owner or ""),
            email=(payload.email or ""),
            settings=payload.settings,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        ts = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
        return {"ok": True, "id": getattr(row, "id", None), "ts": ts}
    except SQLAlchemyError as e:
        db.rollback()
        if DIAG:
            raise HTTPException(status_code=500, detail={"error": "db_error(save)", "type": type(e).__name__, "msg": str(e)})
        raise HTTPException(status_code=500, detail="internal error")
    except Exception as e:
        db.rollback()
        if DIAG:
            raise HTTPException(status_code=500, detail={"error": "save_failed", "type": type(e).__name__, "msg": str(e)})
        raise HTTPException(status_code=500, detail="internal error")

# =====================================
# 読込（ORM → RAW SQL フォールバック）
# =====================================
@router.get("/load")
def load_setting(
    owner: Optional[str] = None,
    email: Optional[str] = None,
    force: Optional[str] = None,
    db: Session = Depends(get_db),
):
    US = getattr(_MODELS, "UserSetting", None)
    if US is None and force != "raw":
        detail = {
            "error": "UserSetting not resolved",
            "models_src": _MODELS_SRC,
            "app_models_file": _APP_MODELS_FILE,
            "root_models_file": _ROOT_MODELS_FILE,
        }
        raise HTTPException(status_code=500, detail=detail)

    orm_err = None

    # 1) ORM（updated_at → created_at → id の降順）
    if force != "raw" and US is not None:
        try:
            q = db.query(US)
            if owner:
                q = q.filter(US.owner == owner)
            if email:
                q = q.filter(US.email == email)

            order_cols = []
            if hasattr(US, "updated_at"):
                order_cols.append(desc(US.updated_at))
            if hasattr(US, "created_at"):
                order_cols.append(desc(US.created_at))
            order_cols.append(desc(US.id))

            row = q.order_by(*order_cols).first()
            if not row:
                raise HTTPException(status_code=404, detail="not found")

            ts = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
            return {"settings": getattr(row, "settings", None), "ts": ts}
        except HTTPException:
            raise
        except Exception as e_orm:
            orm_err = e_orm  # RAW にフォールバック

    # 2) RAW SQL フォールバック（COALESCE で“より新しい方”優先）
    try:
        conds = []
        params: Dict[str, Any] = {}
        if owner:
            conds.append("owner = :owner")
            params["owner"] = owner
        if email:
            conds.append("email = :email")
            params["email"] = email
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        sql = f"""
            SELECT settings, COALESCE(updated_at, created_at) AS ts
            FROM user_settings
            {where}
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT 1
        """
        r = db.execute(text(sql), params).mappings().first()
        if not r:
            raise HTTPException(status_code=404, detail="not found (raw)")

        out = {"settings": r.get("settings"), "ts": r.get("ts"), "note": "raw-fallback"}
        if DIAG and orm_err is not None:
            out["orm_err"] = str(orm_err)
        return out
    except HTTPException:
        raise
    except Exception as e_raw:
        if DIAG:
            raise HTTPException(status_code=500, detail={"error": "load failed", "orm_err": str(orm_err) if orm_err else None, "raw_err": str(e_raw)})
        raise HTTPException(status_code=500, detail="internal error")