# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, logging, math
from datetime import datetime, date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from psycopg2.extras import execute_values, Json
from common_db import connect
from fred_client import fetch_by_name, FredError

def _parse_date_any(s: str | None) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        for fmt in ("%Y/%m/%d", "%Y-%m", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
    return None

def _parse_date_any(s: str | None) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        for fmt in ("%Y/%m/%d", "%Y-%m", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
    return None
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
log = logging.getLogger("macro_ingest")

API_KEY = os.environ.get("FMP_API_KEY")
if not API_KEY:
    log.warning("FMP_API_KEY is not set. Set it before running.")

# FRED のみ使いたい場合は環境変数で制御（"1", "true", "yes", "y" を真と解釈）
USE_FRED_ONLY = os.getenv("USE_FRED_ONLY", "").lower() in ("1", "true", "yes", "y")

# --- FMP endpoints (stable) ---
ECON_URL = "https://financialmodelingprep.com/stable/economic-indicators"  # ?name=GDP など
TREASURY_URL = "https://financialmodelingprep.com/stable/treasury-rates"
INDEX_LIST_URL = "https://financialmodelingprep.com/stable/indexes-list"
HIST_EOD_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"  # ?symbol=GCUSD 等
COMMODITY_LIST_URL = "https://financialmodelingprep.com/stable/commodities-list"

# --- DDL & UPSERT ---
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS macro_features (
  name        text NOT NULL,
  asof_date   date NOT NULL,
  value       numeric,
  meta        jsonb,
  PRIMARY KEY (name, asof_date)
);
"""

UPSERT_SQL = """
INSERT INTO macro_features (name, asof_date, value, meta)
VALUES %s
ON CONFLICT (name, asof_date) DO UPDATE SET
  value = EXCLUDED.value,
  meta  = EXCLUDED.meta;
"""

def _get(url: str, params: Dict[str, Any] | None = None) -> Any:
    params = dict(params or {})
    if API_KEY:
        params.setdefault("apikey", API_KEY)

    def _safe_params(p: Dict[str, Any]) -> Dict[str, Any]:
        s = dict(p)
        if "apikey" in s:
            s["apikey"] = "***"
        return s

    for i in range(5):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(1 + i); continue
            r.raise_for_status()
            return r.json()

        # HTTPエラーはURLにapikeyが含まれることがあるので、URLや例外本文をそのまま出さない
        except requests.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            reason = getattr(e.response, "reason", None)
            log.warning(
                "GET failed %s status=%s reason=%s params=%s try=%s",
                url, code, reason, _safe_params(params), i+1
            )
            time.sleep(1 + i)

        # それ以外の例外もスタックを抑えて安全に
        except Exception as e:
            log.warning(
                "GET failed (non-HTTP) %s type=%s params=%s try=%s",
                url, type(e).__name__, _safe_params(params), i+1
            )
            time.sleep(1 + i)

    raise RuntimeError(f"GET failed: {url}")

# -------- 経済指標（CPI/PPI/CorePCE/UNRATE/FF/GDP） --------
ECON_SERIES: List[Tuple[str, str]] = [
    ("CPI", "CPI"),
    ("PPI", "Producer Price Index"),
    ("CorePCE", "Core PCE Price Index"),
    ("UnemploymentRate", "Unemployment Rate"),
    ("FederalFundsRate", "Federal Funds Rate"),
    ("GDP", "GDP"),
]

# FRED series_id マップ（内部名 → FRED ID）
FRED_NAMES: Dict[str, str] = {
    "CPI": "CPIAUCSL",             # CPI: All Items (Index 1982-84=100)
    "PPI": "PPIACO",               # PPI: All Commodities
    "CorePCE": "PCEPILFE",         # Core PCE (Index 2012=100)
    "UnemploymentRate": "UNRATE",  # Unemployment rate (%)
    "FederalFundsRate": "FEDFUNDS",
    "GDP": "GDPC1",                # Real GDP (Chained 2017$) Quarterly
}

def fetch_economic_indicator(name_param: str) -> List[Tuple[date, float]]:
    """
    FMP /stable/economic-indicators?name=... を叩いて汎用に拾う。
    失敗・空のときは [] を返す（FRED フォールバックは main で実施）。
    """
    # FREDのみモードなら FMP をスキップ
    if USE_FRED_ONLY:
        return []

    alias_map = {
        "CPI": ["CPI", "Consumer Price Index", "CPIAUCSL"],
        "PPI": ["Producer Price Index", "PPI", "PPIACO"],
        "Core PCE Price Index": ["Core PCE Price Index", "Core PCE", "PCEPILFE"],
        "Unemployment Rate": ["Unemployment Rate", "UNRATE"],
        "Federal Funds Rate": ["Federal Funds Rate", "Fed Funds Rate", "FEDFUNDS"],
        "GDP": ["GDP", "Gross Domestic Product", "GDPC1"],
    }
    candidates = alias_map.get(name_param, [name_param])

    for cand in candidates:
        try:
            js = _get(ECON_URL, {"name": cand})
        except Exception as e:
            log.warning("economic-indicators fallback: name=%s ? %s failed (%s)", name_param, cand, e)
            continue

        rows: List[Tuple[date, float]] = []
        if isinstance(js, list):
            for o in js:
                d = _parse_date_any(str(o.get("date") or o.get("dateTime") or o.get("reportedDate") or o.get("publishedDate") or ""))
                v = o.get("value") if "value" in o else (o.get("data") or o.get("actual"))
                try:
                    fv = float(v) if v is not None and str(v).strip() != "" else None
                except Exception:
                    fv = None
                if d and fv is not None and math.isfinite(fv):
                    rows.append((d, fv))

        if rows:
            return rows

    log.warning("economic-indicators failed for all candidates: %s", name_param)
    return []

# -------- 米金利（10Y/2Y）とスロープ --------
def fetch_treasury_10y_2y() -> List[Tuple[str, date, float]]:
    try:
        js = _get(TREASURY_URL, {})
        out: List[Tuple[str, date, float]] = []
        if isinstance(js, list):
            for o in js:
                d = _parse_date_any(str(o.get("date") or ""))
                if not d: continue
                def pick(o: dict, keys: Iterable[str]) -> Optional[float]:
                    for k in keys:
                        if k in o and o[k] is not None:
                            try:
                                return float(o[k])
                            except Exception:
                                pass
                    return None
                y10 = pick(o, ("year10","tenYear","10Y","ten_year","maturity_10_year","Treasury_10Y"))
                y2  = pick(o, ("year2","twoYear","2Y","two_year","maturity_2_year","Treasury_2Y"))
                if y10 is not None:
                    out.append(("US10Y_Yield", d, y10))
                if y2 is not None:
                    out.append(("US2Y_Yield", d, y2))
                if y10 is not None and y2 is not None:
                    out.append(("YieldCurve_10Y_minus_2Y", d, y10 - y2))
        return out
    except Exception as e:
        log.warning("FMP treasury failed (%s); trying FRED fallback (DGS10/DGS2)", e)
        try:
            d10 = fetch_by_name("DGS10")  # 日次10年
            d02 = fetch_by_name("DGS2")   # 日次2年
            map10 = {d: float(v) for d, v in d10}
            map02 = {d: float(v) for d, v in d02}
            dates = sorted(set(map10) | set(map02))
            out: List[Tuple[str, date, float]] = []
            for d in dates:
                if d in map10:
                    out.append(("US10Y_Yield", d, map10[d]))
                if d in map02:
                    out.append(("US2Y_Yield", d, map02[d]))
                if d in map10 and d in map02:
                    out.append(("YieldCurve_10Y_minus_2Y", d, map10[d] - map02[d]))
            return out
        except FredError as fe:
            log.warning("FRED fallback for treasuries failed (%s)", fe)
            return []

# -------- 指数 / コモディティ --------
def resolve_index_symbol_by_name(needle: str) -> Optional[str]:
    try:
        js = _get(INDEX_LIST_URL, {})
        cand = []
        if isinstance(js, list):
            for x in js:
                name = (x.get("name") or "").lower()
                sym = x.get("symbol")
                if needle.lower() in name and sym:
                    cand.append(sym)
        return cand[0] if cand else None
    except Exception:
        return None

def resolve_commodity_symbol(default_sym: str, name_contains: Optional[str] = None) -> str:
    if name_contains is None:
        return default_sym
    try:
        js = _get(COMMODITY_LIST_URL, {})
        if isinstance(js, list):
            for x in js:
                nm = (x.get("name") or "").lower()
                sym = x.get("symbol")
                if name_contains.lower() in nm and sym:
                    return sym
    except Exception:
        pass
    return default_sym

def fetch_hist_eod(symbol: str, max_days: int = 2000) -> List[Tuple[date, float]]:
    js = _get(HIST_EOD_URL, {"symbol": symbol})
    rows: List[Tuple[date, float]] = []
    # 形: {"symbol":"GCUSD","historical":[{"date":"2025-09-16","close":...},...]} または単純リスト
    if isinstance(js, dict) and "historical" in js:
        hist = js.get("historical") or []
        for o in hist:
            d = _parse_date_any(str(o.get("date") or ""))
            c = o.get("close")
            if d and c is not None:
                try:
                    rows.append((d, float(c)))
                except Exception:
                    pass
    elif isinstance(js, list):
        for o in js:
            d = _parse_date_any(str(o.get("date") or ""))
            c = o.get("close")
            if d and c is not None:
                try:
                    rows.append((d, float(c)))
                except Exception:
                    pass
    rows.sort(key=lambda x: x[0])
    if max_days and len(rows) > max_days:
        rows = rows[-max_days:]
    return rows

def pct_change(series: List[Tuple[date, float]], periods: int = 1) -> List[Tuple[date, float]]:
    out: List[Tuple[date, float]] = []
    for i in range(periods, len(series)):
        d, v = series[i]
        pv = series[i - periods][1]
        if pv and pv != 0:
            out.append((d, (v - pv) / pv))
    return out

def yoy_change(series: List[Tuple[date, float]], periods: int = 12) -> List[Tuple[date, float]]:
    return pct_change(series, periods)

def upsert(name: str, rows: List[Tuple[date, float]], meta: Optional[Dict[str, Any]] = None):
    if not rows:
        log.info("no rows for %s", name)
        return

    meta_json = Json(meta) if meta is not None else None

    data = []
    for d, v in rows:
        if d and v is not None and math.isfinite(v):
            data.append((name, d, float(v), meta_json))

    if not data:
        log.info("no valid rows for %s", name)
        return

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_SQL)
            execute_values(cur, UPSERT_SQL, data)
        conn.commit()
    log.info("upserted %s rows into %s", len(data), name)

def main():
    # 1) 経済指標：まずFMP（必要なら）→ データが無い/少ない場合は FRED に置き換え
    econ_cache: Dict[str, List[Tuple[date, float]]] = {}
    for feat_name, econ_name in ECON_SERIES:
        rows = fetch_economic_indicator(econ_name)
        meta: Dict[str, Any] = {"source": "FMP/economic-indicators", "econ_name": econ_name}

        need_min = 12  # 月次系の最低本数（足りない場合は FRED に寄せる）
        fred_id = FRED_NAMES.get(feat_name)

        if (not rows) or (len(rows) < need_min):
            try:
                frows = fetch_by_name(fred_id or feat_name, start="1990-01-01")
                if frows:
                    rows = [(d, float(v)) for d, v in frows]
                    meta = {"source": "FRED", "series_id": fred_id or feat_name}
                    log.warning("FMP empty/short → FRED fallback succeeded for %s", feat_name)
            except FredError as e:
                log.warning("FRED fallback failed for %s (%s)", feat_name, e)

        upsert(feat_name, rows, meta)
        econ_cache[feat_name] = rows

    # 1b) YoY（CPI/PPI/CorePCE=12期間、GDP=四半期なので4期）
    yoy_specs = {
        "CPI": 12,
        "PPI": 12,
        "CorePCE": 12,
        "GDP": 4,
    }
    for base, lag in yoy_specs.items():
        yoy = yoy_change(econ_cache.get(base, []), periods=lag)
        upsert(f"{base}_YoY", yoy, {"derived": "YoY_from_level", "periods": lag})

    # 2) 米金利（10Y/2Y）とスロープ
    try:
        trows = fetch_treasury_10y_2y()
    except Exception as e:
        log.warning("Treasury via FMP failed (%s) — skipping this section.", e)
        trows = []

    by_name: Dict[str, List[Tuple[date, float]]] = {}
    for n, d, v in trows:
        by_name.setdefault(n, []).append((d, v))
    for n, rows in by_name.items():
        rows.sort(key=lambda x: x[0])
        upsert(n, rows, {"source":"FMP/treasury-rates"})

    # 3) 指数/コモディティ
    vix_symbol = "^VIX"
    vix_rows = fetch_hist_eod(vix_symbol)
    upsert("VIX_Close", vix_rows, {"symbol": vix_symbol})

    # DXY → UUP プロキシ（Close と 1日リターン）
    dxy_symbol = "UUP"
    dxy_rows = fetch_hist_eod(dxy_symbol)
    upsert("DXY_Close", dxy_rows, {"symbol": dxy_symbol, "note": "UUP proxy for DXY"})
    upsert("USD_Index_Return", pct_change(dxy_rows, 1), {"from": "DXY_Close", "periods": 1, "note": "UUP proxy"})

    # 金/銅/天然ガス
    gold_sym = resolve_commodity_symbol("GCUSD", "gold")
    copper_sym = resolve_commodity_symbol("HGUSD", "copper")
    gas_sym = resolve_commodity_symbol("NGUSD", "natural gas")

    gold = fetch_hist_eod(gold_sym)
    upsert("Gold_Close", gold, {"symbol": gold_sym})
    upsert("Gold_Return", pct_change(gold), {"periods": 1})

    copper = fetch_hist_eod(copper_sym)
    upsert("Copper_Close", copper, {"symbol": copper_sym})
    upsert("Copper_Return", pct_change(copper), {"periods": 1})

    gas = fetch_hist_eod(gas_sym)
    upsert("NatGas_Close", gas, {"symbol": gas_sym})
    upsert("NatGas_Return", pct_change(gas), {"periods": 1})

    # 4) S&P500（現物指数 ^GSPC を採用）
    es_sym = "^GSPC"
    es = fetch_hist_eod(es_sym)
    upsert("SP500_Close", es, {"symbol": es_sym})
    upsert("SP500_Return", pct_change(es), {"periods": 1})

if __name__ == "__main__":
    main()
