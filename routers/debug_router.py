# routers/debug_router.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from database.database_user import engine

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/dbping")
def dbping():
    """
    純粋なDB接続テスト。SELECT 1 だけ実行（テーブル参照なし）
    成功: {"ok": true, "result": 1}
    失敗: {"ok": false, "type": "...", "error": "..."} を 500 で返す
    """
    try:
        with engine.connect() as con:
            val = con.execute(text("SELECT 1")).scalar_one()
        return {"ok": True, "result": int(val)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "type": e.__class__.__name__, "error": str(e)},
        )

# 参考: 接続先URL（パスワード伏せ）を確認したい時に便利
@router.get("/dbinfo")
def dbinfo():
    try:
        url = engine.url.render_as_string(hide_password=True)
        return {"ok": True, "url": url}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "type": e.__class__.__name__, "error": str(e)},
        )