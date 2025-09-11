# models/__init__.py  (bridge-only)
# Do NOT define tables here. Re-export from app.models.
try:
    from app.models import User, PredictionLog, Owner, UserSetting  # type: ignore
    __all__ = ["User", "PredictionLog", "Owner", "UserSetting"]
except Exception as e:
    # Å’áŒÀ—‚¿‚½——R‚ğŒ©‚¦‚é‰»
    raise
