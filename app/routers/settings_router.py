# app/routers/settings_router.py
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import traceback

# ---- 両対応 import（app.配下 / 直下どちらでも動作）----
try:
    import app.models as models
    from app.db import SessionLocal
    from app.db import Base, engine  # テーブル存在保証の保険（任意）
except Exception:
    import models  # type: ignore
    from db import SessionLocal  # type: ignore
    from db import Base, engine  # type: ignore

router = APIRouter(prefix="/settings", tags=["settings"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SaveIn(BaseModel):
    owner: Optional[str] = None
    email: Optional[str] = None
    settings: Dict[str, Any]

def _ensure_table_exists():
    """
    初回だけ user_settings テーブルの存在を保証（足りなければ create_all）
    既に存在していれば何もしない
    """
    try:
        from sqlalchemy import inspect
        insp = inspect(engine)
        if not insp.has_table(getattr(models.UserSetting, "__tablename__", "user_settings")):
            Base.metadata.create_all(bind=engine)
    except Exception:
        # 無視（存在すればOK）
        pass

@router.post("/save")
def save_setting(payload: SaveIn, db: Session = Depends(get_db)):
    """
    (owner,email) 単位で Upsert する。
    失敗時は 500 で detail と traceback を返す（デバッグ用。一時運用。）
    """
    _ensure_table_exists()
    owner = (payload.owner or "").strip()
    email = (payload.email or "").strip()

    try:
        # 既存の最新1件を探す
        row = (
            db.query(models.UserSetting)
              .filter(models.UserSetting.owner == owner, models.UserSetting.email == email)
              .order_by(models.UserSetting.created_at.desc())
              .first()
        )
        if row:
            row.settings = payload.settings
            row.updated_at = datetime.utcnow()
            db.add(row)
        else:
            row = models.UserSetting(owner=owner, email=email, settings=payload.settings)
            db.add(row)

        db.commit()
        db.refresh(row)
        return {"ok": True, "id": row.id, "ts": row.created_at, "updated": bool(row and owner and email)}
    except Exception as e:
        db.rollback()
        # ★ デバッグ用に詳細を返す（後で外してOK）
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "type": e.__class__.__name__,
                "trace": traceback.format_exc(),
            },
        )

@router.get("/load")
def load_setting(
    owner: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    owner / email 条件での最新1件を返す（created_at の降順）
    失敗時は 500 で detail と traceback を返す（デバッグ用。一時運用。）
    """
    _ensure_table_exists()
    try:
        q = db.query(models.UserSetting)
        if owner:
            q = q.filter(models.UserSetting.owner == owner)
        if email:
            q = q.filter(models.UserSetting.email == email)

        row = q.order_by(models.UserSetting.created_at.desc()).first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")

        return {"settings": row.settings, "ts": row.created_at}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "type": e.__class__.__name__,
                "trace": traceback.format_exc(),
            },
        )