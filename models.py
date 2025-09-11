# models.py  Åiroot / repository top-levelÅj
# Bridge-only: DO NOT define tables here.
# Re-export models from app.models so legacy "import models" keeps working.

from app.models import User, PredictionLog, Owner, UserSetting  # type: ignore

__all__ = ["User", "PredictionLog", "Owner", "UserSetting"]
