# app/routers/settings_router.py
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

# ---- 両対応 import（app.配下 / 直下どちらでも動作）----
try:
    import app.models as models
    from app.db import SessionLocal
except Exception:
    import models  # type: ignore
    from db import SessionLocal  # type: ignore

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

@router.post("/save")
def save_setting(payload: SaveIn, db: Session = Depends(get_db)):
    """
    設定を新規保存（owner + email 単位で複数回保存OK／最新は created_at で判定）
    """
    row = models.UserSetting(
        owner=payload.owner or "",
        email=payload.email or "",
        settings=payload.settings,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id, "ts": row.created_at}

@router.get("/load")
def load_setting(
    owner: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    owner / email 条件での最新1件を返す（created_at の降順）
    """
    q = db.query(models.UserSetting)
    if owner:
        q = q.filter(models.UserSetting.owner == owner)
    if email:
        q = q.filter(models.UserSetting.email == email)

    # ★ここがポイント：最新は created_at の降順で取得
    row = q.order_by(models.UserSetting.created_at.desc()).first()

    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return {"settings": row.settings, "ts": row.created_at}