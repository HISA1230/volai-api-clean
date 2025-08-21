# routers/predict_router.py
# 最小構成の Predict ルーター（重い依存を一切使わない Stub）
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Body

router = APIRouter(prefix="/predict", tags=["Predict"])

# --- 認証依存のフォールバック（auth が無くても起動できるように） ---
try:
    from auth.auth_jwt import get_current_user as _get_current_user  # type: ignore
except Exception:
    def _get_current_user():  # FastAPI の Depends 用のダミー
        class _Dummy:
            id = 0
            email = "demo@example.com"
        return _Dummy()

# メモリ内ログ（本番実装が入るまでの暫定）
_LOGS: List[Dict[str, Any]] = []


@router.get("/logs")
def get_logs(current_user: Any = Depends(_get_current_user)) -> List[Dict[str, Any]]:
    """
    予測ログのスタブ。今は空配列を返すだけ。
    Streamlit 側の UI はこの存在だけで動作可。
    """
    return _LOGS


@router.post("/shap/recompute")
def shap_recompute(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    current_user: Any = Depends(_get_current_user),
) -> Dict[str, Any]:
    """
    SHAP 再計算のスタブ。今は計算せず "stub ok" を返す。
    本実装に差し替えるまでの間、UI と API の配線確認用。
    """
    model_path = (payload or {}).get("model_path")
    return {"message": "stub ok", "model_path": model_path}