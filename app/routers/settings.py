# app/routers/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db, Base, engine
from app.models.user_setting import UserSetting
from app.schemas.user_setting import UserSettingIn, UserSettingOut

router = APIRouter(prefix="/settings", tags=["settings"])

# 初回でも安心なように（Alembic 導入前の暫定）:
# import された時点でテーブルが無ければ作成
Base.metadata.create_all(bind=engine)

@router.get("/{email}", response_model=UserSettingOut)
def get_settings(email: str, db: Session = Depends(get_db)):
    row = db.query(UserSetting).filter(UserSetting.email == email).first()
    if not row:
        # 見つからなければデフォルト値で返す（作成は PUT 時）
        return UserSettingOut(email=email)
    return UserSettingOut(
        email=row.email,
        owner=row.owner,
        notify_enable=row.notify_enable,
        notify_webhook_url=row.notify_webhook_url,
        notify_title=row.notify_title,
        watch_symbols=row.watch_symbols or [],
    )

@router.put("/{email}", response_model=UserSettingOut)
def upsert_settings(email: str, body: UserSettingIn, db: Session = Depends(get_db)):
    row = db.query(UserSetting).filter(UserSetting.email == email).first()
    if not row:
        row = UserSetting(email=email)
        db.add(row)

    row.owner = body.owner
    row.notify_enable = body.notify_enable
    row.notify_webhook_url = body.notify_webhook_url
    row.notify_title = body.notify_title
    row.watch_symbols = body.watch_symbols or []
    db.commit()
    db.refresh(row)

    return UserSettingOut(
        email=row.email,
        owner=row.owner,
        notify_enable=row.notify_enable,
        notify_webhook_url=row.notify_webhook_url,
        notify_title=row.notify_title,
        watch_symbols=row.watch_symbols or [],
    )
