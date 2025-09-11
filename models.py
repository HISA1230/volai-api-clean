# models.py  --- bridge only (do NOT define tables here)
# ルータ等が `import models` しても、実体は app.models.* を使わせるための橋渡し。
from app.models import User, PredictionLog, Owner, UserSetting

__all__ = ["User", "PredictionLog", "Owner", "UserSetting"]