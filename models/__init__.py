# models/__init__.py  (bridge-only; no table definitions)
# Goal: always expose UserSetting even if other submodules are missing.

import os

try:
    # Try aggregate re-export first (may fail if some submodule is missing)
    from app.models import User, PredictionLog, Owner, UserSetting  # type: ignore
    __all__ = ["User", "PredictionLog", "Owner", "UserSetting"]
except Exception as e:
    # Do NOT crash: record error for diag, then try targeted imports
    os.environ["APP_MODELS_IMPORT_ERROR"] = str(e)

    # Targeted, tolerant imports (prefer having UserSetting available)
    try:
        from app.models.user_setting import UserSetting  # type: ignore
    except Exception:
        UserSetting = None  # type: ignore

    try:
        from app.models.owner import Owner  # type: ignore
    except Exception:
        Owner = None  # type: ignore

    try:
        from app.models.user import User  # type: ignore
    except Exception:
        User = None  # type: ignore

    try:
        from app.models.prediction_log import PredictionLog  # type: ignore
    except Exception:
        PredictionLog = None  # type: ignore

    __all__ = [n for n in ("User", "PredictionLog", "Owner", "UserSetting") if globals().get(n) is not None]
