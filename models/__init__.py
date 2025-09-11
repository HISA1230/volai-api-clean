# models/__init__.py  (bridge-only; no table definitions)
# Re-export from app.models, but NEVER raise here (let runtime diag show details)

try:
    from app.models import User, PredictionLog, Owner, UserSetting  # type: ignore
    __all__ = ["User", "PredictionLog", "Owner", "UserSetting"]
except Exception as e:
    # Do not crash the app on deploy; settings/_diag will expose this error.
    import os
    os.environ["APP_MODELS_IMPORT_ERROR"] = str(e)
    __all__ = []
