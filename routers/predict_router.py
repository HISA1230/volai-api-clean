# routers/predict_router.py  --- MINIMAL STUB (no heavy imports) ---
from fastapi import APIRouter

router = APIRouter(prefix="/predict", tags=["Predict"])

@router.get("/logs")
def get_logs():
    # とりあえず空配列（まずは /docs に出すことが目的）
    return []

@router.post("/shap/recompute")
def shap_recompute():
    # まずはスタブでOK（/docsに出るか確認するため）
    return {"message": "stub ok"}
