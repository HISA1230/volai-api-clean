# routers/models_router.py
# -*- coding: utf-8 -*-
"""
依存ゼロの Models ルーター（ファイルベース）
- /models            : モデル一覧 + 既定モデルの取得（GET）
- /models/default    : 既定モデルの取得（GET）、設定（POST）
- /models/rename     : モデルファイルのリネーム（POST）
- /models            : モデルの削除（DELETE）
- /models/meta       : メタ情報の取得（GET）、保存（POST） … .meta.json に保存

認証は“あれば使う”方式（routers.user_router.get_current_user があれば Depends）。
無ければフリーパスで動作します。
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body, Query, Depends
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import time

# ---------------------------
# 認証（存在すれば使う / 無ければ無視）
# ---------------------------
def _noop_dep():
    return None

_auth_dep = _noop_dep
try:
    # あれば使う（例：routers.user_router に get_current_user がある場合）
    from routers.user_router import get_current_user as _real_auth
    _auth_dep = _real_auth  # type: ignore
except Exception:
    pass

router = APIRouter(prefix="/models", tags=["models"])

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)
DEFAULT_FILE = MODELS_DIR / ".default_model.txt"

def _norm(p: Path | str) -> str:
    return str(Path(p).as_posix())

def _meta_path(model_path: str | Path) -> Path:
    base = Path(model_path).with_suffix("")       # models/foo.pkl -> models/foo
    return base.with_suffix(".meta.json")         # -> models/foo.meta.json

def _list_pkls() -> List[Path]:
    return sorted(MODELS_DIR.glob("*.pkl"))

def _file_info(p: Path) -> Dict[str, Any]:
    try:
        st = p.stat()
        return {
            "name": p.name,
            "path": _norm(p),
            "size_bytes": st.st_size,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime)),
        }
    except FileNotFoundError:
        return {"name": p.name, "path": _norm(p), "size_bytes": None, "updated_at": None}

def _load_meta(model_path: Path) -> Dict[str, Any]:
    mp = _meta_path(model_path)
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_meta(model_path: Path, meta: Dict[str, Any]) -> None:
    mp = _meta_path(model_path)
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def _get_default() -> str:
    if DEFAULT_FILE.exists():
        return DEFAULT_FILE.read_text(encoding="utf-8").strip()
    return ""

def _set_default(path: str) -> None:
    DEFAULT_FILE.write_text(path.strip(), encoding="utf-8")

# ---------------------------
# 一覧
# ---------------------------
@router.get("")
def list_models(
    q: Optional[str] = Query(None, description="フリーテキスト（name/description/tags に対して）"),
    tag: Optional[str] = Query(None, description="完全一致のタグフィルタ"),
    current_user: Any = Depends(_auth_dep),
):
    pkls = _list_pkls()
    items: List[Dict[str, Any]] = []
    for p in pkls:
        info = _file_info(p)
        meta = _load_meta(p)
        info["description"] = meta.get("description", "")
        info["display_name"] = meta.get("display_name")
        info["version"] = meta.get("version")
        info["owner"] = meta.get("owner")
        info["tags"] = meta.get("tags", [])
        info["pinned"] = bool(meta.get("pinned", False))
        items.append(info)

    # フィルタ
    if q:
        ql = q.lower()
        items = [
            r for r in items
            if (ql in (r["name"] or "").lower())
            or (ql in (r.get("description") or "").lower())
            or (ql in " ".join(r.get("tags", [])).lower())
            or (ql in (r.get("display_name") or "").lower())
        ]
    if tag:
        items = [r for r in items if tag in (r.get("tags") or [])]

    # pinned を上位
    items.sort(key=lambda r: (not r.get("pinned", False), r.get("name") or ""))

    return {"default_model": _get_default(), "models": items}

# ---------------------------
# 既定モデルの取得
# ---------------------------
@router.get("/default")
def get_default_model(current_user: Any = Depends(_auth_dep)):
    return {"default_model": _get_default()}

# ---------------------------
# 既定モデルの設定
# ---------------------------
@router.post("/default")
def set_default_model(
    body: Dict[str, str] = Body(...),
    current_user: Any = Depends(_auth_dep),
):
    model_path = (body.get("model_path") or "").strip()
    if not model_path:
        raise HTTPException(400, "model_path is required")

    p = Path(model_path)
    if not p.exists():
        # models/ の補正
        p2 = MODELS_DIR / p.name
        if not p2.exists():
            raise HTTPException(404, f"Model not found: {model_path}")
        p = p2

    _set_default(_norm(p))
    return {"message": "default model set", "default_model": _norm(p)}

# ---------------------------
# リネーム
# ---------------------------
@router.post("/rename")
def rename_model(
    body: Dict[str, str] = Body(...),
    current_user: Any = Depends(_auth_dep),
):
    old_name = (body.get("old_name") or "").strip()
    new_name = (body.get("new_name") or "").strip()
    if not old_name or not new_name:
        raise HTTPException(400, "old_name and new_name are required")

    src = MODELS_DIR / old_name
    dst = MODELS_DIR / new_name
    if not src.exists():
        raise HTTPException(404, f"not found: {src}")
    if dst.exists():
        raise HTTPException(409, f"already exists: {dst}")

    # 本体
    src.rename(dst)

    # 付随 SHAP サマリも改名（存在すれば）
    shap_old = MODELS_DIR / (old_name.replace(".pkl", "_shap_summary.csv"))
    shap_new = MODELS_DIR / (new_name.replace(".pkl", "_shap_summary.csv"))
    if shap_old.exists():
        try:
            shap_old.rename(shap_new)
        except Exception:
            pass

    # 既定が旧名なら差し替え
    if _get_default().endswith(old_name):
        _set_default(_norm(dst))

    # メタファイル移設
    meta_old = _meta_path(src)
    meta_new = _meta_path(dst)
    if meta_old.exists():
        try:
            meta_old.rename(meta_new)
        except Exception:
            pass

    return {"ok": True, "new_name": new_name}

# ---------------------------
# 削除
# ---------------------------
@router.delete("")
def delete_model(
    body: Dict[str, str] = Body(...),
    current_user: Any = Depends(_auth_dep),
):
    model_path = (body.get("model_path") or "").strip()
    if not model_path:
        raise HTTPException(400, "model_path is required")

    p = Path(model_path)
    if not p.exists():
        p = MODELS_DIR / Path(model_path).name
    if not p.exists():
        raise HTTPException(404, f"not found: {model_path}")

    if _get_default() == _norm(p):
        raise HTTPException(400, "default model cannot be deleted")

    # 付随 SHAP を削除
    try:
        shap_csv = p.with_suffix("").with_name(p.stem + "_shap_summary.csv")
        if shap_csv.exists():
            shap_csv.unlink()
    except Exception:
        pass

    # 本体削除
    p.unlink(missing_ok=True)

    # メタ削除
    try:
        mp = _meta_path(p)
        if mp.exists():
            mp.unlink()
    except Exception:
        pass

    return {"ok": True, "path": _norm(p)}

# ---------------------------
# メタ情報
# ---------------------------
@router.get("/meta")
def get_model_meta(
    model_path: str = Query(..., description="例: models/vol_model.pkl"),
    current_user: Any = Depends(_auth_dep),
):
    p = Path(model_path)
    if not p.exists():
        p2 = MODELS_DIR / p.name
        if not p2.exists():
            return {"meta": {}}
        p = p2
    return {"meta": _load_meta(p)}

@router.post("/meta")
def set_model_meta(
    body: Dict[str, Any] = Body(...),
    current_user: Any = Depends(_auth_dep),
):
    model_path = (body.get("model_path") or "").strip()
    if not model_path:
        raise HTTPException(400, "model_path is required")

    p = Path(model_path)
    if not p.exists():
        p2 = MODELS_DIR / p.name
        if not p2.exists():
            raise HTTPException(404, f"model not found: {model_path}")
        p = p2

    meta = {
        "display_name": body.get("display_name"),
        "version": body.get("version"),
        "owner": body.get("owner"),
        "description": body.get("description"),
        "tags": body.get("tags") or [],
        "pinned": bool(body.get("pinned", False)),
    }
    _save_meta(p, meta)
    return {"ok": True, "meta": meta}