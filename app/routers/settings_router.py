# app/routers/settings_router.py
from __future__ import annotations

import os
import inspect
from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text, desc

# 識別タグ（/settings/__where で確認用）
ROUTER_SIG = "settings-v6-email-fallback"
router = APIRouter(prefix="/settings", tags=["settings", ROUTER_SIG])

# =========================
# 設定
# =========================
DIAG = os.getenv("SETTINGS_DIAG", "0").lower() not in ("0", "false", "no", "off", "")

# =========================
# DB: app.db / db 両対応
# =========================
def _import_db():
    try:
        from app.db import SessionLocal  # type: ignore
        return SessionLocal, "app.db"
    except Exception:
        from db import SessionLocal  # type: ignore
        return SessionLocal, "db"

SessionLocal, _DB_SRC = _import_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =========================
# models: app.models / models 両対応（UserSetting / Owner を解決）
# =========================
def _get_module_file(mod) -> Optional[str]:
    try:
        return inspect.getfile(mod)  # type: ignore
    except Exception:
        return None

def _import_models() -> Tuple[Any, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    app_err = root_err = None
    app_file = root_file = None

    try:
        import app.models as app_models  # type: ignore
        app_file = _get_module_file(app_models)
        if getattr(app_models, "UserSetting", None) is not None:
            return app_models, "app.models", app_file, None, None, None
        app_err = "app.models.UserSetting is None"
    except Exception as e:
        app_err = repr(e)

    try:
        import models as root_models  # type: ignore
        root_file = _get_module_file(root_models)
        if getattr(root_models, "UserSetting", None) is not None:
            return root_models, "models", None, root_file, app_err, None
        root_err = "models.UserSetting is None"
    except Exception as e:
        root_err = repr(e)

    return None, "(unresolved)", app_file, root_file, app_err, root_err

_MODELS, _MODELS_SRC, _APP_MODELS_FILE, _ROOT_MODELS_FILE, _APP_MODELS_ERR, _ROOT_MODELS_ERR = _import_models()

# =========================
# スキーマ
# =========================
class SaveIn(BaseModel):
    owner: Optional[str] = None
    email: Optional[str] = None
    settings: Dict[str, Any]

# =========================
# 診断/所在（常時登録）
# =========================
@router.get("/__where")
def __where():
    return {
        "file": __file__,
        "sig": ROUTER_SIG,
        "diag": DIAG,
        "models_src": _MODELS_SRC,
        "app_models_file": _APP_MODELS_FILE,
        "root_models_file": _ROOT_MODELS_FILE,
        "has_UserSetting": bool(getattr(_MODELS, "UserSetting", None)),
        "db_src": _DB_SRC,
    }

@router.get("/_diag")
def _diag():
    return {
        "ok": True,
        "env": {"SETTINGS_DIAG": DIAG, "RAW": os.getenv("SETTINGS_DIAG", None)},
        "selected_models_src": _MODELS_SRC,
        "app_models_file": _APP_MODELS_FILE,
        "root_models_file": _ROOT_MODELS_FILE,
        "selected_models_file": _APP_MODELS_FILE if _MODELS_SRC == "app.models" else _ROOT_MODELS_FILE,
        "has_UserSetting": bool(getattr(_MODELS, "UserSetting", None)),
        "app_models_err": _APP_MODELS_ERR,
        "root_models_err": _ROOT_MODELS_ERR,
        "db_src": _DB_SRC,
    }

@router.get("/_peek")
def _peek(
    owner: Optional[str] = None,
    email: Optional[str] = None,
    n: int = Query(5, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if not DIAG:
        raise HTTPException(status_code=404, detail="not found")

    try:
        conds = []
        params: Dict[str, Any] = {"n": n}
        if owner:
            conds.append("owner = :owner")
            params["owner"] = owner
        if email:
            conds.append("email = :email")
            params["email"] = email
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        sql = f"""
            SELECT id, owner, email, settings, created_at, updated_at
            FROM user_settings
            {where}
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT :n
        """
        rows = db.execute(text(sql), params).mappings().all()
        return {"count": len(rows), "items": rows}
    except Exception as e:
        if DIAG:
            raise HTTPException(status_code=500, detail={"error": "peek_failed", "msg": str(e)})
        raise HTTPException(status_code=500, detail="internal error")

# =========================
# 保存（owner の存在チェック付き）
# =========================
from datetime import datetime, timezone

@router.post("/save")
def save_setting(payload: SaveIn, db: Session = Depends(get_db)):
    US = getattr(_MODELS, "UserSetting", None)
    if US is None:
        raise HTTPException(status_code=500, detail={"error": "UserSetting not resolved"})

    owner = (payload.owner or "").strip()
    email = (payload.email or "").strip()
    if not owner or not email:
        raise HTTPException(status_code=400, detail="owner and email are required")

    # Owner の存在検証（いまのまま）
    OwnerM = getattr(_MODELS, "Owner", None)
    if OwnerM is not None:
        exists = db.query(OwnerM).filter(OwnerM.name == owner).first()
        if not exists:
            raise HTTPException(status_code=400, detail=f"unknown owner: {owner}")

    try:
        # ここを追加：同じ owner+email の最新行を探して UPDATE する
        q = db.query(US).filter(US.owner == owner, US.email == email)
        # updated_at が無い環境でも崩れないように安全な降順
        order_cols = []
        if hasattr(US, "updated_at"):
            order_cols.append(desc(US.updated_at))
        if hasattr(US, "created_at"):
            order_cols.append(desc(US.created_at))
        order_cols.append(desc(US.id))
        cur = q.order_by(*order_cols).first()

        if cur:
            # UPDATE
            cur.settings = payload.settings
            if hasattr(cur, "updated_at"):
                cur.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(cur)
            ts = getattr(cur, "updated_at", None) or getattr(cur, "created_at", None)
            return {"ok": True, "id": getattr(cur, "id", None), "ts": ts, "mode": "updated"}

        # なければ INSERT（今まで通り）
        row = US(owner=owner, email=email, settings=payload.settings)  # type: ignore[call-arg]
        db.add(row)
        db.commit()
        db.refresh(row)
        ts = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
        return {"ok": True, "id": getattr(row, "id", None), "ts": ts, "mode": "inserted"}

    except SQLAlchemyError as e:
        db.rollback()
        if DIAG:
            raise HTTPException(status_code=500, detail={"error": "db_error(save)", "type": type(e).__name__, "msg": str(e)})
        raise HTTPException(status_code=500, detail="internal error")

# =====================================
# 読込（まず ORM、だめなら RAW）
# 並び順は “updated_at→created_at→id” の降順
# =====================================
# 変更: /settings/load 本体（中の try 部分だけ差し替え）
@router.get("/load")
def load_setting(
    owner: Optional[str] = None,
    email: Optional[str] = None,
    force: Optional[str] = None,
    db: Session = Depends(get_db),
):
    US = getattr(_MODELS, "UserSetting", None)

    # 1) まず ORM で検索（厳密一致）
    if force != "raw" and US is not None:
        try:
            def _order(q):
                cols = []
                if hasattr(US, "updated_at"):
                    cols.append(desc(US.updated_at))
                if hasattr(US, "created_at"):
                    cols.append(desc(US.created_at))
                cols.append(desc(US.id))
                return q.order_by(*cols)

            q = db.query(US)
            if owner:
                q = q.filter(US.owner == owner)
            if email:
                q = q.filter(US.email == email)

            row = _order(q).first()
            if row:
                ts = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
                return {"settings": getattr(row, "settings", None), "ts": ts}

            # ★ フォールバック：owner+email で見つからなければ email だけで再検索
            if owner and email:
                q2 = db.query(US).filter(US.email == email)
                row2 = _order(q2).first()
                if row2:
                    ts2 = getattr(row2, "updated_at", None) or getattr(row2, "created_at", None)
                    return {
                        "settings": getattr(row2, "settings", None),
                        "ts": ts2,
                        "fallback": "email-only",
                    }
        except Exception:
            # 何かあっても RAW にフォールバック
            pass

    # 2) RAW SQL でも同じロジックでフォールバック
    conds = []
    params: Dict[str, Any] = {}
    if owner:
        conds.append("owner = :owner")
        params["owner"] = owner
    if email:
        conds.append("email = :email")
        params["email"] = email
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    sql = f"""
        SELECT settings, COALESCE(updated_at, created_at) AS ts
        FROM user_settings
        {where}
        ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        LIMIT 1
    """
    r = db.execute(text(sql), params).mappings().first()
    if r:
        return {"settings": r.get("settings"), "ts": r.get("ts"), "note": "raw-strict"}

    # ★ RAW でも無ければ email-only フォールバック
    if owner and email:
        r2 = db.execute(text("""
            SELECT settings, COALESCE(updated_at, created_at) AS ts
            FROM user_settings
            WHERE email = :email
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT 1
        """), {"email": email}).mappings().first()
        if r2:
            return {"settings": r2.get("settings"), "ts": r2.get("ts"), "note": "raw-email-only"}

    # どちらも無ければ 404
    raise HTTPException(status_code=404, detail="not found")

# =====================================
# 診断：API が今 見ている DB の実体 & 必須テーブルの有無
# =====================================
@router.get("/__dbinfo")
def __dbinfo(db: Session = Depends(get_db)):
    try:
        bind = db.get_bind()
        url = bind.url.render_as_string(hide_password=True)
        row = db.execute(text(
            "select current_database(), current_user, inet_server_addr(), inet_server_port()"
        )).fetchone()
        return {
            "ok": True,
            "url": url,
            "current_database": row[0],
            "current_user": row[1],
            "server_addr": str(row[2]),
            "server_port": row[3],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

@router.get("/__dbcheck")
def __dbcheck(db: Session = Depends(get_db)):
    """必須テーブルと Alembic バージョンを簡易チェック"""
    try:
        t_user = db.execute(text("select to_regclass('public.user_settings')")).scalar()
        t_alem = db.execute(text("select to_regclass('public.alembic_version')")).scalar()
        ver = None
        if t_alem:
            ver = db.execute(text("select version_num from alembic_version limit 1")).scalar()
        return {
            "ok": True,
            "has_user_settings": bool(t_user),
            "has_alembic_version": bool(t_alem),
            "alembic_version": ver,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")