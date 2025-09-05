# app/routers/db_router.py
# -*- coding: utf-8 -*-
import os
from fastapi import APIRouter
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/ops", tags=["ops"])

DATABASE_URL = os.getenv("DATABASE_URL")
_engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None

@router.api_route("/dbping", methods=["GET", "HEAD"], include_in_schema=False)
def dbping():
    if _engine is None:
        return {"ok": False, "has_url": False, "error": "DATABASE_URL not set"}
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except SQLAlchemyError as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}