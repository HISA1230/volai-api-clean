from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import date
from app.etl.jobs import job_macro_ingest, job_news_sentiment, job_supply_demand

router = APIRouter(prefix="/ops/jobs", tags=["ops-jobs"])

@router.get("")
def list_jobs_noslash():
    return {"jobs":[
        {"name":"macro_ingest","params":["from (date)","to (date)"]},
        {"name":"news_sentiment","params":["window_hours (int)"]},
        {"name":"supply_demand","params":["date (date)"]},
    ]}
    
@router.api_route("/status", methods=["GET", "HEAD"])

@router.get("/")
def list_jobs_slash():
    return list_jobs_noslash()

@router.post("/run")
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
