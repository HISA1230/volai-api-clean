# app/models/__init__.py ? import modules individually (tolerate missing ones)
try:
    from .user import User  # noqa: F401
except Exception:
    User = None  # type: ignore

try:
    from .prediction_log import PredictionLog  # noqa: F401
except Exception:
    PredictionLog = None  # type: ignore

try:
    from .owner import Owner  # noqa: F401
except Exception:
    Owner = None  # type: ignore

try:
    from .user_setting import UserSetting  # noqa: F401
except Exception:
    UserSetting = None  # type: ignore

__all__ = [n for n in ("User", "PredictionLog", "Owner", "UserSetting") if globals().get(n) is not None]
