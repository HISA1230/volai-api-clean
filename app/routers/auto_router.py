# app/routers/auto_router.py
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

# SessionLocal は app.db / 直下 db の両対応
try:
    from app.db import SessionLocal  # type: ignore
except Exception:
    from db import SessionLocal  # type: ignore

from sqlalchemy import text
import os, uuid, json, datetime as dt

# ✅ ここで /auto プレフィックスを付与（これで /auto/scan になる）
router = APIRouter(prefix="/auto", tags=["auto"])

def _require_cron(auth_header: str | None):
    token = os.getenv("CRON_TOKEN")
    if token:
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        if auth_header.split(" ", 1)[1] != token:
            raise HTTPException(status_code=403, detail="Invalid token")

class AutoScanResult(BaseModel):
    dryrun: bool
    owner: str
    email: str
    actions: list[str] = []
    risk_state: dict | None = None
    notes: list[str] = []

@router.post("/scan", response_model=AutoScanResult)
def scan(
    owner: str = Query(...),
    email: str = Query(...),
    dryrun: bool = Query(False),
    force: str | None = Query(None, pattern="^(tight|normal)$"),
    authorization: str | None = Header(default=None, convert_underscores=False),
):
    _require_cron(authorization)

    with SessionLocal() as db:
        row = db.execute(
            text("""
                SELECT settings, COALESCE(updated_at, created_at) AS ts
                FROM user_settings
                WHERE owner=:owner AND email=:email
                ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                LIMIT 1
            """),
            {"owner": owner, "email": email},
        ).first()

        settings = (row and dict(row._mapping)["settings"]) or {}
        s = dict(settings)  # shallow copy
        s.setdefault("auto_actions", {})
        s.setdefault("risk_state", {"mode": "normal", "since": None, "reason": None})
        actions, notes = [], []
        now_iso = dt.datetime.utcnow().isoformat() + "Z"
        changed = False

        # --- 最小実装：force=normal|tight で動作確認できるように ---
        if force:
            s["risk_state"]["mode"] = force
            s["risk_state"]["since"] = now_iso
            s["risk_state"]["reason"] = f"forced:{force}"
            actions.append(f"risk_state -> {force}")
            changed = True
        else:
            # TODO: 実検知（鮮度/スパイク/レジーム）を追加実装
            notes.append("no-op (heuristics not implemented yet)")

        result = AutoScanResult(
            dryrun=dryrun, owner=owner, email=email,
            actions=actions, risk_state=s.get("risk_state"), notes=notes
        )

        if not dryrun and changed:
            la = s.setdefault("last_auto_actions", [])
            la.append({"at": now_iso, "actions": actions})
            db.execute(
                text("""
                    INSERT INTO user_settings (id, owner, email, settings)
                    VALUES (:id, :owner, :email, :settings::jsonb)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "owner": owner,
                    "email": email,
                    "settings": json.dumps(s),
                },
            )
            db.commit()

        return result