# models.py  （リポジトリ直下 / ルート）
# Bridge-only module: re-export models from app.models for legacy imports.

try:
    # 明示的に名前を出して再エクスポート（mypy/型補完が効きやすい）
    from app.models import User, PredictionLog, Owner, UserSetting
    __all__ = ["User", "PredictionLog", "Owner", "UserSetting"]
except Exception:
    # 上が失敗する環境（パッケージ解決の差異）向けに * も許容
    from app.models import *  # type: ignore