# app/schemas/user_setting.py
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field

class UserSettingIn(BaseModel):
    owner: Optional[str] = None
    notify_enable: bool = False
    notify_webhook_url: Optional[str] = None
    notify_title: str = "VolAI 強シグナル"
    watch_symbols: List[str] = Field(default_factory=list)

class UserSettingOut(UserSettingIn):
    email: EmailStr
