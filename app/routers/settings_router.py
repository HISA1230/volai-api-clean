# app/routers/settings_router.py
from typing import Optional, Dict, Any
import os, traceback
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

# --- 両対応 import（app配下 / 直下）
try:
    import app.models as models
    from app.db import SessionLocal
except Exception:  # pragma: no cover
    import models  # type: ignore
    from db import SessionLocal  # type: ignore

router = APIRouter(prefix="/settings", tags=["settings"])

# 診断フラグ（環境変数）
DIAG = os.getenv("SETTINGS_DIAG", "0").lower() not in ("0", "false", "no", "off")

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

@router.get("/_diag")
def _diag(db: Session = Depends(get_db)):
    """
    設定まわりのセルフチェック（診断用）
    NOTE: SETTINGS_DIAG=1 のときだけ中身を返す。オフ時は 404。
    """
    if not DIAG:
        raise HTTPException(status_code=404, detail="diag disabled")

    info: Dict[str, Any] = {"ok": True, "env": {"SETTINGS_DIAG": True}}
    try:
        # モデル存在チェック
        info["model_module"] = getattr(models, "__name__", str(models))
        info["has_UserSetting"] = hasattr(models, "UserSetting")

        if hasattr(models, "UserSetting"):
            m = models.UserSetting
            info["model_repr"] = repr(m)
            # テーブル情報（列名など）
            try:
                cols = [c.name for c in m.__table__.columns]  # type: ignore
            except Exception:
                cols = []
            info["table_cols"] = cols

            # クイッククエリ（存在行数）※失敗したら理由を返す
            try:
                cnt = db.query(m).count()
                info["row_count"] = cnt
            except Exception as e:
                info["row_count_error"] = {"type": type(e).__name__, "msg": str(e)}
        else:
            info["error"] = "models.UserSetting not found"

    except Exception as e:
        info["ok"] = False
        info["error"] = {"type": type(e).__name__, "msg": str(e), "trace": traceback.format_exc()[-1000:]}
    return info

@router.post("/save")
def save_setting(payload: SaveIn, db: Session = Depends(get_db)):
    try:
        row = models.UserSetting(
            owner=(payload.owner or ""),
            email=(payload.email or ""),
            settings=payload.settings,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"ok": True, "id": row.id, "ts": getattr(row, "created_at", None)}
    except Exception as e:
        db.rollback()
        # 診断ONの時だけ詳細を返す（本番運用ではOFFにしてね）
        if DIAG:
            raise HTTPException(
                status_code=500,
                detail={"error": str(e), "type": type(e).__name__, "trace": traceback.format_exc()[-1200:]},
            )
        raise HTTPException(status_code=500, detail="internal error")

@router.get("/load")
def load_setting(owner: Optional[str] = None,
                 email: Optional[str] = None,
                 db: Session = Depends(get_db)):
    try:
        q = db.query(models.UserSetting)
        if owner:
            q = q.filter(models.UserSetting.owner == owner)
        if email:
            q = q.filter(models.UserSetting.email == email)
        # id が UUID文字列（文字列ソート≒新しい順になりづらい）なので created_at で降順が安全
        row = q.order_by(getattr(models.UserSetting, "created_at", models.UserSetting.id).desc()).first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return {"settings": getattr(row, "settings", {}), "ts": getattr(row, "created_at", None)}
    except HTTPException:
        raise
    except Exception as e:
        if DIAG:
            raise HTTPException(
                status_code=500,
                detail={"error": str(e), "type": type(e).__name__, "trace": traceback.format_exc()[-1200:]},
            )
        raise HTTPException(status_code=500, detail="internal error")