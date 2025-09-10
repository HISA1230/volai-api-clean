# routers/owners.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db, SessionLocal
import models

router = APIRouter(prefix="/owners", tags=["owners"])

@router.get("")
def list_owners(db: Session = Depends(get_db)):
    rows = db.query(models.Owner).order_by(models.Owner.id).all()
    return [{"id": r.id, "name": r.name} for r in rows]
