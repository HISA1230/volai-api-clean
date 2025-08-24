# routers/owners_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body, Query, Depends
from fastapi.responses import JSONResponse
from typing import Any, Dict, Optional
import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# 認証（存在すれば使う / 無ければフリーパス）
def _noop_dep():
    return None

_auth_dep = _noop_dep
try:
    from routers.user_router import get_current_user as _real_auth
    _auth_dep = _real_auth  # type: ignore
except Exception:
    pass

# Engine 取得
try:
    from database.database_user import engine
except Exception:
    engine = None

router = APIRouter(prefix="/owners", tags=["Owners"])

# ベースとなる既定値（足りないキーはここで補完）
DEFAULT_PARAMS: Dict[str, Any] = {
    "universe": {
        "price_min": 0.5,
        "price_max": 100.0,
        "cap_min": 0,
        "cap_max": 50_000_000_000,
        "min_avg_dollar_vol": 1_000_000,
        "sectors": None,
        "symbols_include": None,
        "symbols_exclude": None,
    },
    "training": {
        "cadence_days": 14
    },
}

def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

@router.get("")
def list_owners(current_user: Any = Depends(_auth_dep)):
    if engine is None:
        raise HTTPException(500, "DB engine not configured")
    with engine.connect() as con:
        rows = con.execute(text("SELECT name FROM owners ORDER BY name")).fetchall()
    return [r[0] for r in rows]

@router.get("/settings")
def get_settings(
    owner: Optional[str] = Query(None, description="未指定なら '共用'"),
    current_user: Any = Depends(_auth_dep),
):
    if engine is None:
        raise HTTPException(500, "DB engine not configured")
    o = owner or "共用"
    with engine.connect() as con:
        row = con.execute(text("SELECT params FROM owner_settings WHERE owner=:o"), {"o": o}).fetchone()
    params: Dict[str, Any] = {}
    if row:
        p = row[0]
        if isinstance(p, dict):
            params = p
        elif isinstance(p, str):
            try:
                params = json.loads(p)
            except Exception:
                params = {}
    effective = _deep_merge(DEFAULT_PARAMS, params)
    return {"owner": o, "params": params, "effective": effective}

@router.post("/settings")
def upsert_settings(
    body: Dict[str, Any] = Body(..., description="{'owner': '学也', 'params': {...}}"),
    current_user: Any = Depends(_auth_dep),
):
    if engine is None:
        raise HTTPException(500, "DB engine not configured")

    o = (body.get("owner") or "").strip()
    if not o:
        raise HTTPException(400, "owner is required")
    new_params = body.get("params") or {}
    if not isinstance(new_params, dict):
        raise HTTPException(400, "params must be a JSON object")

    try:
        with engine.begin() as con:
            # オーナーが未登録なら owners に作成
            con.execute(text("INSERT INTO owners(name) VALUES (:o) ON CONFLICT DO NOTHING"), {"o": o})

            # 現在値を取得してマージ
            row = con.execute(text("SELECT params FROM owner_settings WHERE owner=:o"), {"o": o}).fetchone()
            cur: Dict[str, Any] = {}
            if row:
                p = row[0]
                if isinstance(p, dict):
                    cur = p
                elif isinstance(p, str):
                    try:
                        cur = json.loads(p)
                    except Exception:
                        cur = {}

            merged = _deep_merge(cur, new_params)

            # ← ここを環境依存しにくい書き方に（CAST を明示）
            con.execute(
                text("""
                    INSERT INTO owner_settings(owner, params, updated_at)
                    VALUES (:o, CAST(:p AS jsonb), NOW())
                    ON CONFLICT (owner) DO UPDATE
                       SET params = EXCLUDED.params,
                           updated_at = EXCLUDED.updated_at
                """),
                {"o": o, "p": json.dumps(merged, ensure_ascii=False)},
            )

        effective = _deep_merge(DEFAULT_PARAMS, merged)
        return {"ok": True, "owner": o, "params": merged, "effective": effective}

    except SQLAlchemyError as e:
        # ここでエラー内容を JSON で返す（デバッグしやすくする）
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(e).__name__}: {e}"})