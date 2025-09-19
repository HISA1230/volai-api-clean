# app/routers/owners.py
from __future__ import annotations
import os
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

# ==== DB セッション両対応 ====
def _import_db():
    try:
        from app.db import SessionLocal  # type: ignore
        return SessionLocal
    except Exception:
        from db import SessionLocal      # type: ignore
        return SessionLocal

SessionLocal = _import_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(prefix="/owners", tags=["owners"])

def _env_owners() -> List[str]:
    s = os.getenv("OWNERS_LIST", "") or ""
    return [x.strip() for x in s.split(",") if x.strip()]

@router.get("", name="list_owners")
def list_owners(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    DB を優先。ダメなら ENV OWNERS_LIST を返す“安全版”
    返却は JSON シリアライズ済み（文字列のみ）に統一。
    """
    # 1) DB（name だけを文字列で取得）
    try:
        rows = db.execute(text("""
            SELECT name::text AS name
            FROM owners
            ORDER BY name
        """)).mappings().all()
        owners = [r["name"] for r in rows]
        return {"owners": owners, "src": "db"}
    except Exception:
        # 2) ENV フォールバック
        env_list = _env_owners()
        if env_list:
            return {"owners": env_list, "src": "env"}
        # 3) それでも無ければ空配列
        return {"owners": [], "src": "none"}