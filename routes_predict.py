# volatility_ai/routes_predict.py

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Tuple, Any
from datetime import date, time, datetime, timezone, timedelta
import io
import pandas as pd

router = APIRouter(prefix="/predict", tags=["predict"])

# ========= モデル =========
class LogItem(BaseModel):
    ts_utc: datetime
    owner: Optional[str] = None
    time_band: Optional[str] = None
    sector: Optional[str] = None
    size: Optional[str] = None
    symbol: Optional[str] = None
    symbols: Optional[List[str]] = None
    pred_vol: Optional[float] = None
    fake_rate: Optional[float] = None
    confidence: Optional[float] = None
    rec_action: Optional[str] = None
    comment: Optional[str] = None

class SummaryRow(BaseModel):
    date_et: str
    time_band: Optional[str] = None
    sector: Optional[str] = None
    size: Optional[str] = None
    count: int
    avg_pred_vol: Optional[float] = None
    avg_fake_rate: Optional[float] = None
    avg_confidence: Optional[float] = None

# ========= /predict/logs（GET 本体） =========
@router.get("/logs", response_model=List[LogItem])
def get_logs(
    n: int = Query(200, ge=1, le=2000),
    limit: Optional[int] = Query(None, ge=1, le=2000),
    owner: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
):
    """
    ダミーデータを `limit or n` 件返す（新しい順）。UIの挙動検証用。
    """
    lim = min(limit or n, 2000)
    now = datetime.now(timezone.utc)
    items: List[Dict[str, Any]] = []
    for i in range(lim):
        items.append({
            "ts_utc": (now - timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            "owner": owner or "学也H",
            "time_band": ["拡張", "プレ", "レギュラーam", "レギュラーpm", "アフター"][i % 5],
            "sector": ["Tech", "Energy", "Healthcare", "Financials"][i % 4],
            "size": ["Large", "Mid", "Small", "Penny"][i % 4],
            "symbols": [["AAPL", "MSFT", "NVDA", "TSLA"][i % 4]],
            "pred_vol": 0.012 + 0.005 * (i % 6),
            "fake_rate": 0.10 + 0.03 * (i % 5),
            "confidence": 0.40 + 0.08 * (i % 6),
            "rec_action": "watch",
            "comment": "sample",
        })
    return items

# ========= /predict/logs（POST ラッパー） =========
class LogsIn(BaseModel):
    n: Optional[int] = 200
    limit: Optional[int] = None
    owner: Optional[str] = None
    since: Optional[str] = None

@router.post("/logs", response_model=List[LogItem])
def post_logs(p: LogsIn):
    return get_logs(n=p.n or 200, limit=p.limit, owner=p.owner, since=p.since)  # type: ignore

# ========= /predict/logs/summary（GET 本体） =========
def _parse_hhmm(s: Optional[str]) -> Optional[time]:
    if not s:
        return None
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except Exception:
        return None

@router.get(
    "/logs/summary",
    response_model=List[SummaryRow],
    summary="Aggregate logs by date/time_band/sector/size",
)
def get_logs_summary(
    start: Optional[date] = None,
    end: Optional[date] = None,
    time_start: Optional[str] = None,  # "HH:MM"
    time_end: Optional[str] = None,    # "HH:MM"
    tz_offset: int = 0,                # 分。JST=+540, ET(夏)=-240
    owner: Optional[str] = None,
    limit: int = 500,                  # 走査上限
):
    """
    /predict/logs の結果をメモリ集計して返す。
    """
    # 1) 生ログ取得
    raw_items = get_logs(n=limit, limit=limit, owner=owner, since=None)  # type: ignore

    # 2) 辞書 → LogItem へ正規化（両対応）
    items: List[LogItem] = []
    for x in raw_items:
        if isinstance(x, LogItem):
            items.append(x)
        else:
            items.append(LogItem(**x))

    t0 = _parse_hhmm(time_start)
    t1 = _parse_hhmm(time_end)

    agg: Dict[Tuple[str, Optional[str], Optional[str], Optional[str]], Dict[str, float]] = {}
    for it in items:
        ts = it.ts_utc
        # tz_offset（分）を足してローカル時刻に
        local_dt = (ts + timedelta(minutes=tz_offset)).replace(tzinfo=None)
        d_local = local_dt.date()
        tm_local = local_dt.time()

        if start and d_local < start:
            continue
        if end and d_local > end:
            continue
        if t0 and tm_local < t0:
            continue
        if t1 and tm_local > t1:
            continue

        key = (d_local.isoformat(), it.time_band, it.sector, it.size)
        st = agg.setdefault(
            key,
            {
                "count": 0,
                "sum_pred": 0.0, "n_pred": 0,
                "sum_fake": 0.0, "n_fake": 0,
                "sum_conf": 0.0, "n_conf": 0,
            },
        )
        st["count"] += 1
        if it.pred_vol is not None:
            st["sum_pred"] += float(it.pred_vol)
            st["n_pred"] += 1
        if it.fake_rate is not None:
            st["sum_fake"] += float(it.fake_rate)
            st["n_fake"] += 1
        if it.confidence is not None:
            st["sum_conf"] += float(it.confidence)
            st["n_conf"] += 1

    out: List[SummaryRow] = []
    for (d, tb, sec, sz), st in sorted(
        agg.items(),
        key=lambda x: (x[0][0], x[0][1] or "", x[0][2] or "", x[0][3] or ""),
    ):
        out.append(
            SummaryRow(
                date_et=d,
                time_band=tb,
                sector=sec,
                size=sz,
                count=int(st["count"]),
                avg_pred_vol=(st["sum_pred"] / st["n_pred"] if st["n_pred"] else None),
                avg_fake_rate=(st["sum_fake"] / st["n_fake"] if st["n_fake"] else None),
                avg_confidence=(st["sum_conf"] / st["n_conf"] if st["n_conf"] else None),
            )
        )
    return out

# ========= /predict/logs/summary（POST ラッパー） =========
class SummaryIn(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    tz_offset: int = 0
    owner: Optional[str] = None
    limit: int = 500

@router.post("/logs/summary", response_model=List[SummaryRow])
def post_logs_summary(p: SummaryIn):
    return get_logs_summary(
        start=p.start,
        end=p.end,
        time_start=p.time_start,
        time_end=p.time_end,
        tz_offset=p.tz_offset,
        owner=p.owner,
        limit=p.limit,
    )

# ========= /predict/logs/summary.xlsx（Excel エクスポート） =========
def _to_dict(obj: Any) -> Dict[str, Any]:
    # pydantic v2 / v1 両対応
    if hasattr(obj, "model_dump"):
        return obj.model_dump()  # type: ignore[attr-defined]
    if hasattr(obj, "dict"):
        return obj.dict()  # type: ignore[attr-defined]
    return dict(obj)

@router.get("/logs/summary.xlsx")
def get_logs_summary_xlsx(
    start: Optional[date] = None,
    end: Optional[date] = None,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    tz_offset: int = 0,
    owner: Optional[str] = None,
    limit: int = 500,
):
    rows = get_logs_summary(
        start=start,
        end=end,
        time_start=time_start,
        time_end=time_end,
        tz_offset=tz_offset,
        owner=owner,
        limit=limit,
    )

    df = pd.DataFrame([_to_dict(r) for r in rows])

    buf = io.BytesIO()
    # openpyxl が無ければエラーになるので、必要に応じて requirements に追加
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="summary")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename=\"logs_summary.xlsx\"'},
    )