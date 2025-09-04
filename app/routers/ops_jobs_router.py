# app/routers/ops_jobs_router.py
# -*- coding: utf-8 -*-
from typing import Optional
from datetime import date

from fastapi import APIRouter, Query, HTTPException, Depends

from app.auth_guard import API_REQUIRE_JWT, require_user, require_admin
from app.etl.jobs import job_macro_ingest, job_news_sentiment, job_supply_demand

# JWT を使う場合は閲覧もログイン必須にする（不要なら [] にしてもOK）
deps_user = [Depends(require_user)] if API_REQUIRE_JWT else []

router = APIRouter(prefix="/ops/jobs", tags=["ops-jobs"], dependencies=deps_user)

@router.get("")
def list_jobs_noslash():
    return {
        "jobs": [
            {"name": "macro_ingest",   "params": ["from (date)", "to (date)"]},
            {"name": "news_sentiment", "params": ["window_hours (int)"]},
            {"name": "supply_demand",  "params": ["day (date)"]},
        ]
    }

@router.get("/")
def list_jobs_slash():
    return list_jobs_noslash()

# ★ 実行だけ管理者トークンを要求
@router.post("/run", dependencies=[Depends(require_admin)])
def run_job(
    name: str = Query(..., description="macro_ingest | news_sentiment | supply_demand"),
    frm: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = None,
    window_hours: int = 6,
    day: Optional[date] = None,
):
    if name == "macro_ingest":
        return job_macro_ingest(frm, to)
    if name == "news_sentiment":
        return job_news_sentiment(window_hours=window_hours)
    if name == "supply_demand":
        return job_supply_demand(target_date=day)
    raise HTTPException(400, f"unknown job: {name}")