# routers/models_router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
import glob
import json
from datetime import datetime

from auth.auth_jwt import get_current_user
from database.database_user import get_db
from sqlalchemy.orm import Session
from models.models_user import UserModel, ModelMeta

router = APIRouter(prefix="/models", tags=["Models"])

MODELS_DIR = "models"
DEFAULT_FILE = os.path.join(MODELS_DIR, ".default_model.txt")

# ---------- Input Schemas ----------
class SetDefaultBody(BaseModel):
    model_path: str = Field(..., description="モデルのパス（例: models/vol_model.pkl）", alias="model_path")

class RenameBody(BaseModel):
    old_name: str
    new_name: str

class DeleteBody(BaseModel):
    model_path: str

class ModelMetaIn(BaseModel):
    model_path: str
    display_name: Optional[str] = None
    version: Optional[str] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    pinned: Optional[bool] = False

# ---------- Helpers ----------
def _default_model_path() -> str:
    if os.path.exists(DEFAULT_FILE):
        try:
            with open(DEFAULT_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""

def _write_default(path: str):
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(DEFAULT_FILE, "w", encoding="utf-8") as f:
        f.write(path)

def _file_info(p: str) -> Dict[str, Any]:
    try:
        stat = os.stat(p)
        return {
            "name": os.path.basename(p),
            "path": p.replace("\\", "/"),
            "size_bytes": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    except FileNotFoundError:
        return {
            "name": os.path.basename(p),
            "path": p.replace("\\", "/"),
            "size_bytes": None,
            "updated_at": None
        }

def _load_meta_bulk(db: Session, model_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """model_path -> meta dict"""
    rows = db.query(ModelMeta).filter(ModelMeta.model_path.in_(model_paths)).all()
    out = {}
    for r in rows:
        out[r.model_path] = {
            "display_name": r.display_name,
            "version": r.version,
            "owner": r.owner,
            "description": r.description,
            "tags": r.tags or [],
            "pinned": r.pinned,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
    return out

# ---------- Endpoints ----------
@router.get("")
def list_models(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="フリーテキスト検索（名前/説明/タグに対して）"),
    tag: Optional[str] = Query(None, description="タグでフィルタ（完全一致）"),
):
    os.makedirs(MODELS_DIR, exist_ok=True)
    pkls = sorted(glob.glob(os.path.join(MODELS_DIR, "*.pkl")))
    default_path = _default_model_path()

    # 基本ファイル情報
    infos = [_file_info(p) for p in pkls]
    model_paths = [i["path"] for i in infos]

    # メタをDBからまとめて取得
    meta_map = _load_meta_bulk(db, model_paths)

    # メタをマージ
    enriched = []
    for info in infos:
        meta = meta_map.get(info["path"], {})
        row = {
            **info,
            "display_name": meta.get("display_name"),
            "version": meta.get("version"),
            "owner": meta.get("owner"),
            "description": meta.get("description"),
            "tags": meta.get("tags", []),
            "pinned": meta.get("pinned", False),
        }
        enriched.append(row)

    # フィルタリング
    def match_q(r):
        if not q:
            return True
        text = " ".join([
            r.get("name") or "",
            r.get("display_name") or "",
            r.get("description") or "",
            " ".join(r.get("tags") or []),
        ]).lower()
        return q.lower() in text

    def match_tag(r):
        if not tag:
            return True
        return tag in (r.get("tags") or [])

    filtered = [r for r in enriched if match_q(r) and match_tag(r)]

    # pinned を上位に
    filtered.sort(key=lambda r: (not r.get("pinned", False), r.get("name") or ""))

    return {
        "default_model": default_path,
        "models": filtered
    }

@router.get("/default")
def get_default_model(current_user: UserModel = Depends(get_current_user)):
    return {"default_model": _default_model_path()}

@router.post("/default")
def set_default_model(
    body: SetDefaultBody,
    current_user: UserModel = Depends(get_current_user),
):
    model_path = body.model_path
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail="Model file not found")
    _write_default(model_path)
    return {"message": "default model set", "default_model": model_path}

@router.post("/rename")
def rename_model(
    body: RenameBody,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    old_path = os.path.join(MODELS_DIR, body.old_name)
    new_path = os.path.join(MODELS_DIR, body.new_name)

    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="Old model not found")
    if os.path.exists(new_path):
        raise HTTPException(status_code=400, detail="New name already exists")

    # 本体
    os.rename(old_path, new_path)

    # 付随SHAPファイルもリネーム（あれば）
    base_old = os.path.splitext(old_path)[0]
    base_new = os.path.splitext(new_path)[0]
    for suffix in ["_shap_values.pkl", "_shap_summary.csv"]:
        op = base_old + suffix
        np = base_new + suffix
        if os.path.exists(op):
            try:
                os.rename(op, np)
            except Exception:
                pass

    # 既定が旧名なら更新
    if _default_model_path() == old_path.replace("\\", "/"):
        _write_default(new_path.replace("\\", "/"))

    # メタも path を更新
    meta = db.query(ModelMeta).filter(ModelMeta.model_path == old_path.replace("\\", "/")).first()
    if meta:
        meta.model_path = new_path.replace("\\", "/")
        db.commit()

    return {"message": "renamed", "new_name": body.new_name}

@router.delete("")
def delete_model(
    body: DeleteBody,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = body.model_path
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Model not found")

    if _default_model_path() == p.replace("\\", "/"):
        raise HTTPException(status_code=400, detail="Default model cannot be deleted")

    os.remove(p)

    # 付随SHAPも削除
    base = os.path.splitext(p)[0]
    for suffix in ["_shap_values.pkl", "_shap_summary.csv"]:
        sp = base + suffix
        if os.path.exists(sp):
            try:
                os.remove(sp)
            except Exception:
                pass

    # メタも削除
    meta = db.query(ModelMeta).filter(ModelMeta.model_path == p.replace("\\", "/")).first()
    if meta:
        db.delete(meta)
        db.commit()

    return {"message": "deleted", "path": p}

# ===== メタ情報(DB) =====
@router.get("/meta")
def get_model_meta(
    model_path: str = Query(..., description="モデルパス（例: models/vol_model.pkl）"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meta = db.query(ModelMeta).filter(ModelMeta.model_path == model_path).first()
    if not meta:
        return {"meta": {}}
    return {
        "meta": {
            "display_name": meta.display_name,
            "version": meta.version,
            "owner": meta.owner,
            "description": meta.description,
            "tags": meta.tags or [],
            "pinned": meta.pinned,
            "created_at": meta.created_at.isoformat() if meta.created_at else None,
            "updated_at": meta.updated_at.isoformat() if meta.updated_at else None,
        }
    }

@router.post("/meta")
def upsert_model_meta(
    body: ModelMetaIn,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not os.path.exists(body.model_path):
        raise HTTPException(status_code=404, detail="Model file not found")

    row = db.query(ModelMeta).filter(ModelMeta.model_path == body.model_path).first()
    if not row:
        row = ModelMeta(model_path=body.model_path)

    row.display_name = body.display_name
    row.version = body.version
    row.owner = body.owner
    row.description = body.description
    row.tags = body.tags or []
    row.pinned = bool(body.pinned)

    db.add(row)
    db.commit()
    return {"message": "meta saved"}