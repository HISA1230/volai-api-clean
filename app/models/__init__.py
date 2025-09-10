# app/models/__init__.py
from .user import User
from .prediction_log import PredictionLog
from .owner import Owner
from .user_setting import UserSetting   # ★これを追加
__all__ = ["User", "PredictionLog", "Owner", "UserSetting"]