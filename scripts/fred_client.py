# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import datetime as dt
from typing import List, Tuple, Optional

import requests


FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class FredError(RuntimeError):
    pass


# 人間向け名称 / プロジェクト内部名 / シリーズID のいずれでも解決できるマップ
# 例: "Unemployment Rate", "UnemploymentRate", "UNRATE" の全部を UNRATE に解決
NAME_MAP = {
    # human-friendly
    "cpi": "CPIAUCSL",
    "core pce price index": "PCEPILFE",
    "unemployment rate": "UNRATE",
    "federal funds rate": "FEDFUNDS",
    "gdp": "GDPC1",
    "ppi": "PPIACO",
    
    "dgs10": "DGS10",
    "dgs2":  "DGS2",
    # project-internal (Camel/Pascal風)
    "corepce": "PCEPILFE",
    "unemploymentrate": "UNRATE",
    "federalfundsrate": "FEDFUNDS",

    # series ids (そのまま受け付け)
    "cpiaucsl": "CPIAUCSL",
    "pcepilfe": "PCEPILFE",
    "unrate": "UNRATE",
    "fedfunds": "FEDFUNDS",
    "gdpc1": "GDPC1",
    "ppiaco": "PPIACO",
}


def _resolve_series_id(name: str) -> Optional[str]:
    if not name:
        return None
    s1 = name.strip().lower()
    s2 = s1.replace(" ", "")
    return NAME_MAP.get(s2) or NAME_MAP.get(s1)


def _read_env_file(name: str) -> str | None:
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        pass
    return None

def _get_api_key() -> str:
    api_key = os.getenv("FRED_API_KEY") or _read_env_file("FRED_API_KEY")
    if not api_key:
        raise FredError("FRED_API_KEY is not set (env/.env).")
    return api_key


def _fetch_series(series_id: str,
                  start: Optional[str] = None,
                  end: Optional[str] = None) -> List[Tuple[dt.date, float]]:
    if not start:
        start = "1990-01-01"
    if not end:
        end = dt.date.today().isoformat()

    params = {
        "series_id": series_id,
        "api_key": _get_api_key(),
        "file_type": "json",
        "observation_start": start,
        "observation_end": end,
    }
    try:
        r = requests.get(FRED_BASE, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        raise FredError(f"FRED GET failed ({series_id}): {e}") from e

    obs = js.get("observations", [])
    out: List[Tuple[dt.date, float]] = []
    for o in obs:
        d = o.get("date")
        v = o.get("value")
        if not d or v in (None, "", "."):
            continue
        try:
            out.append((dt.date.fromisoformat(d), float(v)))
        except Exception:
            pass
    return out


def fetch_by_name(name: str,
                  start: Optional[str] = None,
                  end: Optional[str] = None) -> List[Tuple[dt.date, float]]:
    """
    name には人間向け名称・内部名・シリーズIDのいずれを渡してもOK。
    例: 'Unemployment Rate' / 'UnemploymentRate' / 'UNRATE'
    """
    sid = _resolve_series_id(name)
    if not sid:
        raise FredError(f"Unknown indicator name for FRED fallback: {name}")
    return _fetch_series(sid, start=start, end=end)