# streamlit_app.py — Volatility AI Minimal UI (final unified, minimal fixes)
# - Keep original layout/labels
# - Latest predictions: fallback /api/predict/latest -> /predict/latest
# - Logs: default limit 2000
# - Summary: owner not applied by default (toggleable)
# - SHAP: robust, manual model input if discovery 404; diagnostics collapsed

# ------------ imports ------------
import os
import io
import json
import traceback
import base64
from typing import Optional, Dict, Any, List, Tuple, TYPE_CHECKING
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Optional chart lib for heatmap
try:
    import altair as alt
except Exception:
    alt = None

load_dotenv(override=False)

# ------------ query params helper ------------
def _qp() -> Dict[str, Any]:
    try:
        return st.query_params
    except Exception:
        return st.experimental_get_query_params()

def _qpick(q: Dict[str, Any], key: str) -> str:
    if not q:
        return ""
    v = q.get(key)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return ("" if v is None else str(v)).strip()

# ------------ API resolver（単一の真実）------------
def resolve_api_base() -> str:
    q = _qp()
    if q and ("api" in q) and q["api"]:
        v = q["api"][0] if isinstance(q["api"], list) else q["api"]
        v = str(v).strip().rstrip("/")
        if v:
            return v
    for k in ("API_URL", "API_BASE", "PUBLIC_API_BASE", "VOLAI_API_BASE"):
        v = (os.getenv(k) or "").strip().rstrip("/")
        if v:
            return v
    if os.getenv("RENDER") or "onrender.com" in (os.getenv("RENDER_EXTERNAL_URL") or ""):
        return "https://webmasters-fill-confidence-runtime.trycloudflare.com"
    return "http://127.0.0.1:8010"

API: str = resolve_api_base()
SWAGGER_URL: str = f"{API}/docs"

def _is_full_url(u: str) -> bool:
    return isinstance(u, str) and (u.startswith("http://") or u.startswith("https://"))

def _build_url(path_or_url: str) -> str:
    return path_or_url if _is_full_url(path_or_url) else f"{API}/{path_or_url.lstrip('/')}"

# ------------ requests.Session（再試行つき）------------
_session: Optional[requests.Session] = None

def get_session() -> requests.Session:
    global _session
    if _session is not None:
        return _session
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "VolAI-UI/1.0 (+streamlit)",
        "Accept": "application/json, text/plain, */*",
    })
    _session = s
    return s

# ------------ 統一HTTPヘルパー ------------
def req(
    method: str,
    path_or_url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    data: Any = None,
    headers: Optional[Dict[str, str]] = None,
    files: Any = None,
    timeout: int | float | tuple = 20,
    auth: bool = False,
    retry_on_401: bool = True,
    retries: int = 0,
    quiet_httpcodes: Optional[set] = None,
):
    url = _build_url(path_or_url)
    s = get_session()

    def _get_token() -> str:
        return st.session_state.get("token", "") or ""

    def _auth_headers() -> Dict[str, str]:
        tok = _get_token()
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def ensure_auth(force: bool = False) -> bool:
        if force:
            st.session_state["token"] = ""
        if _get_token():
            return True
        if _magic_login():
            return True
        return _basic_login()

    def _magic_login() -> bool:
        tok = (os.getenv("AUTOLOGIN_TOKEN") or os.getenv("ADMIN_TOKEN") or "").strip()
        if not tok:
            return False
        url_login = _build_url("/auth/magic_login")
        resp = s.post(url_login, json={"token": tok}, timeout=15)
        if not resp.ok and resp.status_code in (400, 422):
            email = (os.getenv("API_EMAIL") or "").strip()
            resp = s.post(url_login, json={"token": tok, "email": email}, timeout=15)
        if resp.ok:
            st.session_state["token"] = resp.json().get("access_token", "")
            return bool(st.session_state.get("token"))
        return False

    def _basic_login() -> bool:
        email = (os.getenv("API_EMAIL") or "").strip()
        pw    = (os.getenv("API_PASSWORD") or "").strip()
        if not email or not pw:
            return False
        url_login = _build_url("/login")
        resp = s.post(url_login, json={"email": email, "password": pw}, timeout=15)
        if resp.ok:
            st.session_state["token"] = resp.json().get("access_token", "")
            return bool(_get_token())
        return False

    hdrs: Dict[str, str] = {}
    hdrs.update(headers or {})
    if auth:
        if not _get_token() and not ensure_auth():
            raise RuntimeError("Authentication failed: no token available")
        hdrs.update(_auth_headers())

    last_err: Optional[Exception] = None
    quiet_httpcodes = quiet_httpcodes or set()

    for attempt in range(max(1, int(retries) + 1)):
        try:
            resp = s.request(
                method.upper(), url,
                params=params, json=json_data, data=data, files=files,
                headers=hdrs, timeout=timeout,
            )
            if resp.status_code == 401 and auth and retry_on_401:
                if ensure_auth(force=True):
                    hdrs.update(_auth_headers())
                    resp = s.request(method.upper(), url,
                                     params=params, json=json_data, data=data, files=files,
                                     headers=hdrs, timeout=timeout)
            resp.raise_for_status()

            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype:
                return resp.json()
            try:
                return resp.json()
            except Exception:
                return resp.text

        except (requests.ReadTimeout, requests.ConnectTimeout) as e:
            last_err = e
            if attempt + 1 < max(1, int(retries) + 1):
                import time as _t; _t.sleep(0.7 * (2 ** attempt))
                continue
            st.error(f"Timeout: {e}")
            raise
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            body = getattr(getattr(e, "response", None), "text", "") or str(e)
            if status not in quiet_httpcodes:
                st.error(f"HTTP {status}: {body or e}")
            raise
        except Exception as e:
            last_err = e
            st.error(f"Request error: {e}")
            raise
    if last_err:
        raise last_err

# --- owners の安全取得（API → ダメならフォールバック） ---
@st.cache_data(ttl=300)
def safe_owners(api_base: str) -> Tuple[List[str], str]:
    if (os.getenv("UI_SKIP_OWNERS_API") or "").strip():
        return _fallback_owners(), "forced-fallback"
    try:
        r = requests.get(f"{api_base}/owners", timeout=3)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("owners"), list):
            src = data.get("src", "api")
            lst = data["owners"]
        else:
            src = "api"
            lst = data
        names: List[str] = []
        if isinstance(lst, list):
            for x in lst:
                if isinstance(x, str):
                    names.append(x)
                elif isinstance(x, dict):
                    nm = x.get("name") or x.get("owner") or x.get("id")
                    if nm: names.append(str(nm))
        if names:
            return names, src
    except Exception:
        pass
    return _fallback_owners(), "fallback"

def _fallback_owners() -> List[str]:
    raw = os.getenv("FALLBACK_OWNERS", "学也H,共用,学也,正恵,正恵M")
    return [x.strip() for x in raw.split(",") if x.strip()]

@st.cache_data(ttl=600)
def discover_log_endpoints(api_base: str) -> List[str]:
    import re
    s = get_session()
    allow = re.compile(r"(?i)(?:^|/)(?:.*(?:/|^)(?:log|logs|history|events?|records?))(?:/|$)")
    deny  = re.compile(r"(?i)/(?:login|logout|catalog|blog|logic)(?:/|$)")

    tried = []
    for path in ("/openapi.json", "/api/openapi.json"):
        try:
            r = s.get(f"{api_base.rstrip('/')}{path}", timeout=5)
            if not r.ok:
                tried.append(f"{path} -> HTTP {r.status_code}")
                continue
            spec = r.json()
            paths = list((spec.get("paths") or {}).keys())
            cands = []
            for p in paths:
                pp = "/" + p.lstrip("/")
                if deny.search(pp):
                    continue
                if allow.search(pp):
                    cands.append(pp)
            out = sorted(dict.fromkeys(cands), key=lambda x: (len(x), x))
            st.session_state["_logs_discovered_from"] = path
            return out
        except Exception as e:
            tried.append(f"{path} -> {type(e).__name__}: {e}")
            continue
    st.session_state["_logs_discovered_from"] = f"(not found: {', '.join(tried)})"
    return []

# ------------ pandas Styler 型 ------------
if TYPE_CHECKING:
    try:
        from pandas.io.formats.style import Styler as PDStyler
    except Exception:
        PDStyler = Any  # type: ignore
else:
    PDStyler = Any

# =========================
# 基本設定
# =========================
SHOW_WEBHOOK_UI = (os.getenv("SHOW_WEBHOOK_UI", "1").lower() not in ("0","false","no","off"))
st.set_page_config(page_title="Volatility AI UI", layout="wide")

def set_query_params_safe(**params):
    try:
        st.query_params.clear()
        st.query_params.update(params)
    except Exception:
        st.experimental_set_query_params(**params)

def api_has(path: str) -> bool:
    url = f"{API}{path}"
    for m in ("HEAD","GET"):
        try:
            r = requests.request(m, url, timeout=5)
            if r.status_code in (200,401,405): return True
            if r.status_code == 404: return False
        except Exception:
            pass
    return False

def to_utc_series(ts_col) -> pd.Series:
    s = pd.to_datetime(ts_col, errors="coerce", utc=True)
    if not s.isna().all():
        return s
    for unit in ("s", "ms", "us", "ns"):
        s = pd.to_datetime(ts_col, unit=unit, errors="coerce", utc=True)
        if not s.isna().all():
            return s
    return pd.to_datetime(pd.Series([None]*len(ts_col)), errors="coerce", utc=True)

# =========================
# セッション既定値
# =========================
st.session_state.setdefault("diff_on", True)
st.session_state.setdefault("snap_prev", pd.DataFrame())
st.session_state.setdefault("live_prev", pd.DataFrame())
st.session_state.setdefault("alert_seen_snap", set())
st.session_state.setdefault("alert_seen_live", set())

st.session_state.setdefault("auto_refresh_on", False)
st.session_state.setdefault("auto_refresh_sec", 60)
st.session_state.setdefault("auto_refresh_live_first", True)

st.session_state.setdefault("profiles", {})
st.session_state.setdefault("profile_name", "")

st.session_state.setdefault("token", None)
st.session_state.setdefault("me", None)
st.session_state.setdefault("owner_pick", None)

st.session_state.setdefault("ui_preset", "一般的")
st.session_state.setdefault("ui_sizes", [])
st.session_state.setdefault("auto_fill_ranges", True)
st.session_state.setdefault("auto_adjust_thresholds_by_size", True)

for k, v in {"pv_y":0.012,"pv_r":0.040,"fr_o":0.25,"fr_r":0.50,"cf_a":0.40,"cf_h":0.70}.items():
    st.session_state.setdefault(k, v)

st.session_state.setdefault("price_min_in", 0.0)
st.session_state.setdefault("price_max_in", 0.0)
st.session_state.setdefault("mkt_min_in",   0.0)
st.session_state.setdefault("mkt_max_in",   0.0)

st.session_state.setdefault("run_has_result", False)
st.session_state.setdefault("last_counts", (0,0))
st.session_state.setdefault("snap_raw", pd.DataFrame())
st.session_state.setdefault("live_raw", pd.DataFrame())
st.session_state.setdefault("snap_filtered", pd.DataFrame())
st.session_state.setdefault("live_filtered", pd.DataFrame())
st.session_state.setdefault("notes_joined", "")
st.session_state.setdefault("cmp_df", pd.DataFrame())
st.session_state.setdefault("summary_defaults", (None,None))
st.session_state.setdefault("last_sizes_for_ranges", tuple())
st.session_state.setdefault("steps_snap", [])
st.session_state.setdefault("steps_live", [])
st.session_state.setdefault("debug_window", {})
st.session_state.setdefault("debug_preview", pd.DataFrame())
st.session_state.setdefault("debug_timefix", {})

st.session_state.setdefault("notify_webhook_url", "")
st.session_state.setdefault("notify_enable", False)
st.session_state.setdefault("notify_title", "VolAI 強シグナル")
st.session_state.setdefault("notified_keys_snap", set())
st.session_state.setdefault("notified_keys_live", set())

# Logs panel UX state
st.session_state.setdefault("logs_panel_open", False)
st.session_state.setdefault("_scroll_to_logs", False)
st.session_state.setdefault("logs_cached_df", pd.DataFrame())

# SHAP viewer state
st.session_state.setdefault("shap_summary_df", pd.DataFrame())
st.session_state.setdefault("shap_summary_src", "")
st.session_state.setdefault("shap_models", [])
st.session_state.setdefault("shap_models_src", "")
st.session_state.setdefault("shap_model_pick", "")
st.session_state.setdefault("shap_topk", 30)
st.session_state.setdefault("_shap_tried", [])

# ---- URLからの自動復元（初回のみ）
if not st.session_state.get("loaded_from_url", False):
    q = _qp()
    try:
        cfg_b64 = (q.get("cfg") or [""])[0] if q else ""
        if cfg_b64:
            def _b64_decode(s: str) -> Dict[str, Any]:
                s = s.strip(); s += "=" * (-len(s) % 4)
                return json.loads(base64.urlsafe_b64decode(s.encode("utf-8")))
            from datetime import date as _date
            def apply_settings_from_url(cfg: Dict[str, Any]) -> None:
                for k, v in cfg.items(): st.session_state[k] = v
                td = st.session_state.get("target_date")
                if isinstance(td, str) and td:
                    try: st.session_state["target_date"] = _date.fromisoformat(td)
                    except Exception: pass
            apply_settings_from_url(_b64_decode(cfg_b64))
            st.session_state["loaded_from_url"] = True
            st.toast("URLの設定を復元しました", icon="✅")
    except Exception:
        pass

# === SHAP/Models パスの URL 上書き（常時・差分だけ反映） ===
try:
    q_now = _qp()
except Exception:
    q_now = {}

shap_q   = _qpick(q_now, "shap")
models_q = _qpick(q_now, "models")

applied = False
if shap_q and shap_q != st.session_state.get("shap_summary_override"):
    st.session_state["shap_summary_override"] = shap_q
    applied = True
if models_q and models_q != st.session_state.get("shap_models_override"):
    st.session_state["shap_models_override"] = models_q
    applied = True

if applied:
    try: st.cache_data.clear()
    except Exception: pass
    try: st.cache_resource.clear()
    except Exception: pass
    st.toast(f"URL上書きを反映: shap={shap_q or '-'} / models={models_q or '-'}", icon="✅")
    st.rerun()

# =========================
# しきい値（プリセット）
# =========================
Thresholds = Dict[str, Dict[str, float]]
PRESETS: Dict[str, Thresholds] = {
    "relaxed":  {"pred_vol":{"yellow":0.008,"red":0.030}, "fake_rate":{"orange":0.30,"red":0.60}, "confidence":{"attention":0.30,"high":0.60}},
    "standard": {"pred_vol":{"yellow":0.012,"red":0.040}, "fake_rate":{"orange":0.25,"red":0.50}, "confidence":{"attention":0.40,"high":0.70}},
    "strict":   {"pred_vol":{"yellow":0.018,"red":0.060}, "fake_rate":{"orange":0.20,"red":0.40}, "confidence":{"attention":0.50,"high":0.80}},
}
PRESET_LABELS = {"relaxed": "緩め", "standard": "標準", "strict": "厳しめ"}
PRESET_LABELS_INV = {v: k for k, v in PRESET_LABELS.items()}

def normalize_preset_name(x: Optional[str]) -> str:
    if not isinstance(x, str): return ""
    x = x.strip()
    if x in PRESETS: return x
    return PRESET_LABELS_INV.get(x, x)

st.session_state.setdefault("th_preset", "standard")
st.session_state.setdefault("threshold_profiles", {})

def apply_threshold_preset(preset_name: str) -> None:
    p = PRESETS.get(preset_name)
    if not p: return
    st.session_state["pv_y"] = float(p["pred_vol"]["yellow"])
    st.session_state["pv_r"] = float(p["pred_vol"]["red"])
    st.session_state["fr_o"] = float(p["fake_rate"]["orange"])
    st.session_state["fr_r"] = float(p["fake_rate"]["red"])
    st.session_state["cf_a"] = float(p["confidence"]["attention"])
    st.session_state["cf_h"] = float(p["confidence"]["high"])

def current_thresholds_dict() -> Dict[str, float]:
    return {
        "pv_y": float(st.session_state["pv_y"]),
        "pv_r": float(st.session_state["pv_r"]),
        "fr_o": float(st.session_state["fr_o"]),
        "fr_r": float(st.session_state["fr_r"]),
        "cf_a": float(st.session_state["cf_a"]),
        "cf_h": float(st.session_state["cf_h"]),
    }

def load_thresholds_from_dict(d: Dict[str, Any]) -> None:
    for k in ("pv_y","pv_r","fr_o","fr_r","cf_a","cf_h"):
        if k in d: st.session_state[k] = float(d[k])

# =========================
# 取得・時刻付与
# =========================
TS_CANDIDATES = ["ts_utc","ts","timestamp","time_utc","time","datetime","created_at","updated_at"]

def attach_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df["_ts_utc"] = pd.NaT
        return df
    used = None
    for col in TS_CANDIDATES:
        if col in df.columns:
            s = to_utc_series(df[col])
            if not s.isna().all():
                df["_ts_utc"] = s
                used = col
                break
    if "_ts_utc" not in df.columns:
        df["_ts_utc"] = pd.NaT
    try:
        tz = ZoneInfo("America/Toronto")
        df["_ts_et"] = df["_ts_utc"].dt.tz_convert(tz)
        df["_date_et"] = df["_ts_et"].dt.date
        df["_time_et"] = df["_ts_et"].dt.strftime("%H:%M")
    except Exception:
        pass
    st.session_state["last_ts_source"] = used
    st.session_state["last_ts_nonnull"] = int(df["_ts_utc"].notna().sum())
    st.session_state["last_ts_total"] = int(len(df))
    return df

# --- 型/値チェック & 正規化（attach_time_columns の直後に追加） ---
REQUIRED_LATEST = {
    "pred_vol": float, "fake_rate": float, "confidence": float,
}
ALT_NAMES = {
    "pred_vol":  ["predicted_vol","vol_pred","volatility_pred","pv"],
    "fake_rate": ["fraud_rate","noise_rate","fr"],
    "confidence":["conf","score"],
}

def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    # 別名→正規名
    for main, alts in ALT_NAMES.items():
        if main not in d.columns:
            for a in alts:
                if a in d.columns:
                    d = d.rename(columns={a: main})
                    break
    # 必須列の作成 & 数値化
    for c in REQUIRED_LATEST:
        if c not in d.columns:
            d[c] = pd.NA
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d

def sanitize_latest_df(df: pd.DataFrame) -> pd.DataFrame:
    d = _ensure_cols(df)
    # 想定レンジにクリップ（0〜1）
    for c in ("pred_vol","fake_rate","confidence"):
        if c in d.columns:
            d[c] = d[c].clip(lower=0, upper=1)
    return d

# ---- 最新取得（/api が404なら /predict に自動フォールバック） ----
def fetch_latest(n: int, mode_live: bool=False) -> Tuple[pd.DataFrame, Optional[str]]:
    paths = ["/api/predict/latest", "/predict/latest"]
    params = {"n": int(n)}
    if mode_live:
        params["mode"] = "live"
    last_err = None
    for p in paths:
        try:
            res = req("GET", p, params=params, auth=False, timeout=20, quiet_httpcodes={404})
            df = pd.DataFrame(res)
            if df.empty:
                return df, None
            df = sanitize_latest_df(df)
            for c in ("price","market_cap"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            df = attach_time_columns(df)
            cols = [c for c in [
                "_ts_utc","ts_utc","_ts_et","_date_et","_time_et","time_band","sector","size",
                "pred_vol","fake_rate","confidence","rec_action","symbols","comment","price","market_cap","symbol"
            ] if c in df.columns]
            return df[cols] if cols else df, None
        except Exception as e:
            last_err = e
            continue
    return pd.DataFrame(), (str(last_err) if last_err else "not found")

# ② fetch_logs（既定上限を 2000 に）
@st.cache_data(ttl=120)
def fetch_logs(limit: int = 2000, owner: Optional[str] = None, since_iso: Optional[str] = None) -> pd.DataFrame:
    override = (st.session_state.get("logs_path_override") or "").strip()
    discovered = discover_log_endpoints(API)

    candidates: List[str] = []
    if override:
        candidates.append(override)
    candidates.extend(discovered)
    candidates.extend([
        "/predict/logs",
        "/api/predict/logs",
        "/predict/history",
        "/api/predict/history",
        "/logs",
        "/api/logs",
        "/api/v1/logs",
    ])

    # 正規化 & ノイズ除去
    norm: List[str] = []
    seen = set()
    for c in candidates:
        c = "/" + str(c).lstrip("/")
        if c not in seen:
            seen.add(c)
            norm.append(c)
    candidates = norm

    BAD = {"login", "logout", "catalog", "blog", "logic"}
    def _bad(p: str) -> bool:
        return any(part in BAD for part in p.lower().split("/"))
    candidates = [c for c in candidates if not _bad(c)]

    params: Dict[str, Any] = {"n": int(limit), "limit": int(limit)}
    if owner:
        params["owner"] = owner
    if since_iso:
        params["since"] = since_iso

    used_path: Optional[str] = None

    for base in candidates:
        for path in (base, base + "/"):
            # --- GET 試行 ---
            try:
                data = req("GET", path, params=params, auth=True, timeout=30,
                           quiet_httpcodes={404, 405, 422})
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    data = data["items"]

                df = pd.DataFrame(data)
                used_path = path

                if not df.empty:
                    df = sanitize_latest_df(df)
                    for c in ("price", "market_cap"):
                        if c in df.columns:
                            df[c] = pd.to_numeric(df[c], errors="coerce")

                    df = attach_time_columns(df)

                    cols = [c for c in [
                        "_ts_utc","_ts_et","_date_et","_time_et",
                        "owner","time_band","sector","size","symbol","symbols",
                        "pred_vol","fake_rate","confidence","rec_action","comment",
                        "price","market_cap"
                    ] if c in df.columns]
                    if cols:
                        df = df[cols]
                    if "_ts_utc" in df.columns:
                        df = df.sort_values("_ts_utc", ascending=False).reset_index(drop=True)

                st.session_state["_logs_endpoint_used"] = used_path
                st.session_state["_logs_endpoint_missing"] = False
                st.session_state["_logs_endpoint_candidates"] = candidates
                return df

            except requests.HTTPError as e:
                stt = getattr(getattr(e, "response", None), "status_code", None)
                # --- 405 → POST 再試行 ---
                if stt == 405:
                    try:
                        data = req("POST", path, json_data=params, auth=True, timeout=30,
                                   quiet_httpcodes={404, 405, 422})
                        if isinstance(data, dict) and isinstance(data.get("items"), list):
                            data = data["items"]

                        df = pd.DataFrame(data)
                        used_path = path

                        if not df.empty:
                            df = sanitize_latest_df(df)
                            for c in ("price","market_cap"):
                                if c in df.columns:
                                    df[c] = pd.to_numeric(df[c], errors="coerce")

                            df = attach_time_columns(df)

                            cols = [c for c in [
                                "_ts_utc","_ts_et","_date_et","_time_et",
                                "owner","time_band","sector","size","symbol","symbols",
                                "pred_vol","fake_rate","confidence","rec_action","comment",
                                "price","market_cap"
                            ] if c in df.columns]
                            if cols:
                                df = df[cols]
                            if "_ts_utc" in df.columns:
                                df = df.sort_values("_ts_utc", ascending=False).reset_index(drop=True)

                        st.session_state["_logs_endpoint_used"] = used_path
                        st.session_state["_logs_endpoint_missing"] = False
                        st.session_state["_logs_endpoint_candidates"] = candidates
                        return df
                    except Exception:
                        continue
                else:
                    continue
            except Exception:
                continue

    # どれも失敗
    st.session_state["_logs_endpoint_missing"] = True
    st.session_state["_logs_endpoint_candidates"] = candidates
    return pd.DataFrame()

def resolve_target_date_for_filter(target_date_et: Optional[date], df_ref: pd.DataFrame) -> Optional[date]:
    if target_date_et is not None: return target_date_et
    try:
        if "_ts_utc" in df_ref.columns and not df_ref["_ts_utc"].isna().all():
            tz = ZoneInfo("America/Toronto")
            return df_ref["_ts_utc"].dt.tz_convert(tz).dt.date.max()
    except Exception:
        pass
    return None

# === Summary helpers (API優先→空ならフォールバック) ===
SUMMARY_PATH_CANDIDATES = [
    "/predict/logs/summary",
    "/api/predict/logs/summary",
    "/logs/summary",
    "/api/logs/summary",
]

def _extract_list_like(obj) -> List[Dict[str, Any]]:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("items", "data", "summary", "rows", "result"):
            v = obj.get(k)
            if isinstance(v, list):
                return v
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], (dict, list)):
                return v
    return []

def fetch_logs_summary_api(params: Dict[str, Any]) -> Tuple[pd.DataFrame, str]:
    for path in SUMMARY_PATH_CANDIDATES:
        for use_auth in (True, False):
            # GET
            try:
                r = req("GET", path, params=params, auth=use_auth, timeout=20,
                        quiet_httpcodes={404, 405, 422})
                rows = _extract_list_like(r)
                return pd.DataFrame(rows), f"api:{path}[GET]:auth{'Y' if use_auth else 'N'}"
            except Exception:
                pass
            # POST
            try:
                r = req("POST", path, json_data=params, auth=use_auth, timeout=20,
                        quiet_httpcodes={404, 405, 422})
                rows = _extract_list_like(r)
                return pd.DataFrame(rows), f"api:{path}[POST]:auth{'Y' if use_auth else 'N'}"
            except Exception:
                pass
    return pd.DataFrame(), "api:none"

def _local_time(dt_utc: pd.Timestamp, tz_offset_min: int) -> Optional[datetime]:
    if pd.isna(dt_utc):
        return None
    return (dt_utc.tz_convert("UTC").to_pydatetime().replace(tzinfo=ZoneInfo("UTC"))
            + timedelta(minutes=tz_offset_min))

def _band_label(h: int, m: int) -> str:
    t = h*60 + m
    if  4*60+30 <= t < 9*60+30:   return "プレ（04:30–09:30 ET）"
    if  9*60+30 <= t < 12*60:     return "レギュラーam（09:30–12:00 ET）"
    if 12*60     <= t < 16*60:    return "レギュラーpm（12:00–16:00 ET）"
    if 16*60     <= t <= 20*60:   return "アフター（16:00–20:00 ET）"
    return "(その他)"

def build_summary_fallback_from_logs(params: Dict[str, Any]) -> Tuple[pd.DataFrame, str]:
    owner = params.get("owner") or None
    limit = int(params.get("limit") or 2000)
    tz_offset = int(params.get("tz_offset") or 0)
    t0 = params.get("time_start")
    t1 = params.get("time_end")
    start_d = params.get("start")
    end_d = params.get("end")

    df_logs = fetch_logs(limit=limit, owner=owner, since_iso=None)
    if df_logs.empty:
        return pd.DataFrame(), "fallback:logs=0"

    df = df_logs.copy()
    df["_local_dt"] = df["_ts_utc"].apply(lambda x: _local_time(x, tz_offset))
    df["_local_date"] = df["_local_dt"].apply(lambda x: x.date() if x else None)
    df["_local_h"] = df["_local_dt"].apply(lambda x: x.hour if x else None)
    df["_local_m"] = df["_local_dt"].apply(lambda x: x.minute if x else None)
    df["time_band"] = df.apply(
        lambda r: _band_label(int(r["_local_h"]), int(r["_local_m"])) if pd.notna(r["_local_h"]) else "(その他)",
        axis=1
    )

    if start_d:
        try:
            sd = date.fromisoformat(start_d) if isinstance(start_d, str) else start_d
            df = df[df["_local_date"] >= sd]
        except Exception:
            pass
    if end_d:
        try:
            ed = date.fromisoformat(end_d) if isinstance(end_d, str) else end_d
            df = df[df["_local_date"] <= ed]
        except Exception:
            pass

    def _to_min(s):
        try:
            h, m = map(int, s.split(":"))
            return h*60 + m
        except Exception:
            return None

    t0m = _to_min(t0) if t0 else None
    t1m = _to_min(t1) if t1 else None
    if t0m is not None and t1m is not None:
        lm = df["_local_h"]*60 + df["_local_m"]
        df = df[(lm >= t0m) & (lm <= t1m)]

    for c in ("pred_vol","fake_rate","confidence"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    grp_cols = ["_local_date","time_band"]
    if "sector" in df.columns: grp_cols.append("sector")
    if "size"   in df.columns: grp_cols.append("size")
    if not set(grp_cols).issubset(df.columns):
        return pd.DataFrame(), "fallback:cols-missing"

    g = df.groupby(grp_cols, dropna=False).agg(
        count=("pred_vol","size"),
        avg_pred_vol=("pred_vol","mean"),
        avg_fake_rate=("fake_rate","mean"),
        avg_confidence=("confidence","mean"),
    ).reset_index()

    g = g.rename(columns={"_local_date":"date_et"})
    for c in ("avg_pred_vol","avg_fake_rate","avg_confidence"):
        if c in g.columns:
            g[c] = g[c].round(3)

    return g, "fallback:client-aggregate"

# === DF normalize helpers (safe) ===
def _safe_to_date(x):
    if pd.isna(x):
        return None
    try:
        # pandas/pyarrow Timestamp, datetime.date どちらも OK
        if hasattr(x, "date"):  # Timestamp/Datetime
            d = x.date() if not isinstance(x, date) else x
            return d
        # 文字列（ISO, YYYY-MM-DD, など）に対応
        if isinstance(x, str) and x.strip():
            dt = pd.to_datetime(x, errors="coerce", utc=False)
            if pd.isna(dt):
                return None
            try:
                return dt.date()  # tz-naive/aware 両対応
            except Exception:
                return None
    except Exception:
        return None
    return None

def _coerce_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    """logs summary で来る date_et/time_band 列の最終ガード"""
    d = df.copy()
    if "date_et" in d.columns:
        d["date_et"] = d["date_et"].apply(_safe_to_date)
    # 平均列が str で来ても死なないように
    for c in ("avg_pred_vol", "avg_fake_rate", "avg_confidence"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    if "count" in d.columns:
        d["count"] = pd.to_numeric(d["count"], errors="coerce").fillna(0).astype(int)
    return d

# === 表示用ヘルパー（日本語表示・色バッジ） ===
def _badge_vol(v: float) -> str:
    if pd.isna(v): return ""
    pv_y, pv_r = float(st.session_state["pv_y"]), float(st.session_state["pv_r"])
    if v >= pv_r:   mark = "🟥"
    elif v >= pv_y: mark = "🟨"
    else:           mark = "🟩"
    return f"{mark} {v:.3f}"

def _badge_fake(v: float) -> str:
    if pd.isna(v): return ""
    fr_o, fr_r = float(st.session_state["fr_o"]), float(st.session_state["fr_r"])
    if v >= fr_r:   mark = "🟥"
    elif v >= fr_o: mark = "🟧"
    else:           mark = "🟩"
    return f"{mark} {v:.3f}"

def _badge_conf(v: float) -> str:
    if pd.isna(v): return ""
    cf_a, cf_h = float(st.session_state["cf_a"]), float(st.session_state["cf_h"])
    if v >= cf_h:      return f"🟢 {v:.2f} 高信頼"
    elif v >= cf_a:    return f"🟠 {v:.2f} 注意"
    else:              return f"🔴 {v:.2f} 信頼低"

def _et_time_window(ts_et: pd.Timestamp, minutes: int = 60) -> str:
    if pd.isna(ts_et): return ""
    t0 = ts_et.to_pydatetime()
    t1 = (ts_et + pd.Timedelta(minutes=minutes)).to_pydatetime()
    return f"{t0:%H:%M}–{t1:%H:%M}"

def _fmt_m_d(x) -> str:
    """日付/日時/文字列/NaT を 'M/D' で安全に表示"""
    # None / NaT
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass

    # 文字列はまずパース
    if isinstance(x, str):
        x = pd.to_datetime(x, errors="coerce")
        if pd.isna(x):
            return ""

    # pandas.Timestamp -> date
    if isinstance(x, pd.Timestamp):
        try:
            x = x.to_pydatetime().date()
        except Exception:
            pass

    # datetime.datetime -> date
    from datetime import datetime as _dt, date as _date
    if isinstance(x, _dt):
        x = x.date()

    # date を整形（OS差分に対応）
    if isinstance(x, _date):
        try:
            return x.strftime("%-m/%-d")     # Linux/Mac
        except Exception:
            try:
                return x.strftime("%#m/%#d") # Windows
            except Exception:
                return f"{x.month}/{x.day}"

    # 最後の保険
    m = getattr(x, "month", None)
    d = getattr(x, "day", None)
    if m is not None and d is not None:
        try:
            return f"{int(m)}/{int(d)}"
        except Exception:
            return f"{m}/{d}"
    return ""

def _to_jp_table(df: pd.DataFrame) -> pd.DataFrame:
    """最新行/ログ行を日本語＆色バッジで表示用に整形"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["日付","予測時間帯","セクター","サイズ","予測ボラ","だまし率","信頼度","APIコメント"])

    d = df.copy()
    if "_ts_utc" in d.columns:
        d = d.sort_values("_ts_utc", ascending=False)

    def pick(col, default=""):
        return d[col] if col in d.columns else default

    date_col = pick("_date_et", pd.NaT)
    time_col = pick("_ts_et", pd.NaT)

    out = pd.DataFrame({
        "日付":        [(_fmt_m_d(x) if not pd.isna(x) else "") for x in date_col],
        "予測時間帯":  [(_et_time_window(x) if not pd.isna(x) else "") for x in time_col],
        "セクター":    pick("sector", ""),
        "サイズ":      pick("size", ""),
        "予測ボラ":    d["pred_vol"].apply(_badge_vol)    if "pred_vol" in d.columns else "",
        "だまし率":    d["fake_rate"].apply(_badge_fake)  if "fake_rate" in d.columns else "",
        "信頼度":      d["confidence"].apply(_badge_conf) if "confidence" in d.columns else "",
        "APIコメント": pick("comment", ""),
    })
    for c in out.columns:
        out[c] = out[c].fillna("")
    return out

def _to_jp_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """ログ・サマリーを日本語＆色バッジで表示用に整形（型ゆるく来ても落ちない）"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["日付","時間帯","セクター","サイズ","件数","平均ボラ","平均だまし率","平均信頼度"])

    d = _coerce_summary_df(df.copy())  # ★ここで型を整える

    def pick(col, default=""):
        return d[col] if col in d.columns else default

    date_col = pick("date_et", pd.Series([None]*len(d)))
    out = pd.DataFrame({
        "日付":         [(_fmt_m_d(x) if x else "") for x in date_col],
        "時間帯":       pick("time_band", ""),
        "セクター":     pick("sector", ""),
        "サイズ":       pick("size", ""),
        "件数":         pick("count", 0),
        "平均ボラ":     (d["avg_pred_vol"].apply(_badge_vol)    if "avg_pred_vol"    in d.columns else ""),
        "平均だまし率": (d["avg_fake_rate"].apply(_badge_fake)  if "avg_fake_rate"   in d.columns else ""),
        "平均信頼度":   (d["avg_confidence"].apply(_badge_conf) if "avg_confidence"  in d.columns else ""),
    })
    for c in out.columns:
        out[c] = out[c].fillna("")
    return out

def _to_jp_shap_table(df: pd.DataFrame) -> pd.DataFrame:
    """SHAP サマリーを日本語列名に整形"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["特徴量","平均|SHAP|","平均SHAP","符号"])
    d = normalize_shap_summary(df.copy())
    out = pd.DataFrame({
        "特徴量":       d["feature"],
        "平均|SHAP|":   pd.to_numeric(d["mean_abs_shap"], errors="coerce").round(6) if "mean_abs_shap" in d.columns else pd.NA,
        "平均SHAP":     pd.to_numeric(d["mean_shap"],     errors="coerce").round(6) if "mean_shap"     in d.columns else pd.NA,
        "符号":         d["sign"].map({"pos":"＋","neg":"−"}).fillna("±") if "sign" in d.columns else "",
    })
    for c in out.columns:
        out[c] = out[c].fillna("")
    return out
# === SHAP helpers（一覧404でも手入力でOK） ===
SHAP_MODELS_PATH_FALLBACK = [
    "/models", "/api/models",
    "/model/list", "/api/model/list",
    "/api/v1/models", "/api/v1/model/list",
]
SHAP_SUMMARY_PATH_FALLBACK = [
    "/explain/shap_summary", "/api/explain/shap_summary",
    "/predict/explain/shap_summary", "/api/predict/explain/shap_summary",
    "/shap/summary", "/api/shap/summary",
    "/shap_summary", "/api/shap_summary",
    "/models/shap_summary", "/api/models/shap_summary",
    "/predict/shap_summary", "/api/predict/shap_summary",
    "/explain/shap/summary", "/api/explain/shap/summary",
    "/api/v1/explain/shap_summary", "/api/v1/shap/summary",
    "/explain/global_importance", "/api/explain/global_importance",
    "/feature_importance", "/api/feature_importance",
    "/explain/feature_importance", "/api/explain/feature_importance",
    "/api/v1/feature_importance", "/api/v1/explain/global_importance",
]

def _extract_list_like_any(obj):
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("items", "data", "rows", "result", "summary", "models", "features", "top"):
            v = obj.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                try:
                    return [{"feature": kk, "mean_abs_shap": vv} for kk, vv in v.items()]
                except Exception:
                    pass
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], (dict, list, str, int, float)):
                return v
        try:
            return [{"feature": k, "mean_abs_shap": v} for k, v in obj.items()
                    if isinstance(k, str) and isinstance(v, (int, float))]
        except Exception:
            pass
        return []
    if isinstance(obj, str):
        if ("\n" in obj) and ("," in obj or "\t" in obj):
            try:
                sep = "\t" if "\t" in obj and obj.count("\t") >= obj.count(",") else ","
                df = pd.read_csv(io.StringIO(obj), sep=sep)
                return df.to_dict(orient="records")
            except Exception:
                return []
    return []

def normalize_shap_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["feature","mean_abs_shap","mean_shap","sign"])
    d = df.copy()
    rename_map = {}
    for cand in ["feature","name","col","variable","feature_name","field"]:
        if cand in d.columns:
            rename_map[cand] = "feature"; break
    for cand in ["mean_abs_shap","mean_abs","abs_mean_shap","mean_abs_value","importance","abs_shap","value","score"]:
        if cand in d.columns:
            rename_map[cand] = "mean_abs_shap"; break
    for cand in ["mean_shap","mean","avg_shap","mean_value","shap_mean"]:
        if cand in d.columns:
            rename_map[cand] = "mean_shap"; break
    d = d.rename(columns=rename_map)
    if "feature" not in d.columns and d.shape[1] == 2:
        d.columns = ["feature", d.columns[1]]
    if "feature" not in d.columns:
        d = d.reset_index(drop=False).rename(columns={"index":"feature"})
    if "mean_abs_shap" not in d.columns and "mean_shap" in d.columns:
        d["mean_abs_shap"] = pd.to_numeric(d["mean_shap"], errors="coerce").abs()
    if "mean_abs_shap" not in d.columns:
        num_cols = [c for c in d.columns if c != "feature" and pd.api.types.is_numeric_dtype(d[c])]
        if num_cols:
            d["mean_abs_shap"] = pd.to_numeric(d[num_cols[0]], errors="coerce").abs()
        else:
            d["mean_abs_shap"] = pd.NA
    if "mean_shap" not in d.columns:
        d["mean_shap"] = pd.NA
    def _sign(x):
        try:
            return "pos" if float(x) > 0 else ("neg" if float(x) < 0 else "±")
        except Exception:
            return "±"
    d["sign"] = d["mean_shap"].apply(_sign)
    keep = ["feature","mean_abs_shap","mean_shap","sign"]
    return d[[c for c in keep if c in d.columns]]

@st.cache_data(ttl=300)
def fetch_models_list() -> Tuple[List[str], str]:
    candidates = SHAP_MODELS_PATH_FALLBACK[:]
    override = (st.session_state.get("shap_models_override")
                or os.getenv("SHAP_MODELS_PATH_HINT") or "").strip()
    if override:
        candidates = [override] + [c for c in candidates if c != override]
    for path in candidates:
        for use_auth in (True, False):
            # GET
            try:
                r = req("GET", path, auth=use_auth, timeout=15, quiet_httpcodes={404,405,422})
                rows = _extract_list_like_any(r)
                names: List[str] = []
                for it in rows:
                    if isinstance(it, str):
                        names.append(it)
                    elif isinstance(it, dict):
                        nm = it.get("name") or it.get("model") or it.get("id")
                        if nm: names.append(str(nm))
                if not names and isinstance(r, dict) and isinstance(r.get("models"), list):
                    for it in r["models"]:
                        if isinstance(it, str): names.append(it)
                        elif isinstance(it, dict):
                            nm = it.get("name") or it.get("model") or it.get("id")
                            if nm: names.append(str(nm))
                if names:
                    names = sorted(dict.fromkeys(names))
                    return names, f"api:{path}[GET]:auth{'Y' if use_auth else 'N'}"
            except Exception:
                pass
            # POST
            try:
                r = req("POST", path, json_data={}, auth=use_auth, timeout=15, quiet_httpcodes={404,405,422})
                rows = _extract_list_like_any(r)
                names: List[str] = []
                for it in rows:
                    if isinstance(it, str):
                        names.append(it)
                    elif isinstance(it, dict):
                        nm = it.get("name") or it.get("model") or it.get("id")
                        if nm: names.append(str(nm))
                if names:
                    names = sorted(dict.fromkeys(names))
                    return names, f"api:{path}[POST]:auth{'Y' if use_auth else 'N'}"
            except Exception:
                pass
    return [], "api:none"

@st.cache_data(ttl=300)
def fetch_shap_summary_api(model: str,
                           owner: Optional[str] = None,
                           topk: Optional[int] = None) -> Tuple[pd.DataFrame, str]:
    candidates = SHAP_SUMMARY_PATH_FALLBACK[:]
    override = (st.session_state.get("shap_summary_override")
                or os.getenv("SHAP_SUMMARY_PATH_HINT") or "").strip()
    if override:
        candidates = [override] + [c for c in candidates if c != override]
    # try GET→POST with parameter variants
    variants: List[Dict[str, Any]] = []
    if topk and int(topk) > 0:
        for k in ("topk","top_k","k","top","limit","n","max_features"):
            variants.append({"model": model, k: int(topk)})
    else:
        variants.append({"model": model})
    if owner:
        for v in list(variants):
            vv = dict(v); vv["owner"] = owner; variants.append(vv)
    for path in candidates:
        for use_auth in (True, False):
            for p in variants:
                try:
                    r = req("GET", path, params=p, auth=use_auth, timeout=20, quiet_httpcodes={404,405,422})
                    rows = _extract_list_like_any(r)
                    df = normalize_shap_summary(pd.DataFrame(rows))
                    if not df.empty:
                        return df, f"api:{path}[GET]:auth{'Y' if use_auth else 'N'}"
                except Exception:
                    pass
            for p in variants:
                try:
                    r = req("POST", path, json_data=p, auth=use_auth, timeout=20, quiet_httpcodes={404,405,422})
                    rows = _extract_list_like_any(r)
                    df = normalize_shap_summary(pd.DataFrame(rows))
                    if not df.empty:
                        return df, f"api:{path}[POST]:auth{'Y' if use_auth else 'N'}"
                except Exception:
                    pass
    return pd.DataFrame(), "api:none"

# =========================
# ヘッダ & サイドバー
# =========================
st.title("Volatility AI – Minimal UI")
st.caption(f"API Base: {API} ｜ Swagger: {SWAGGER_URL}")

with st.sidebar:
    st.subheader("ログイン")
    default_email = os.getenv("API_EMAIL", "test@example.com")
    default_pass  = os.getenv("API_PASSWORD", "test1234")
    email = st.text_input("Email", value=default_email, key="login_email")
    password = st.text_input("Password", type="password", value=default_pass, key="login_password")
    st.caption(f"🔌 API = {API} ｜ env.API_URL={os.getenv('API_URL','(unset)')}")

    AUTOLOGIN_TOKEN = os.getenv("AUTOLOGIN_TOKEN") or os.getenv("ADMIN_TOKEN")

    def try_autologin_once():
        if st.session_state.get("_autologin_done"):
            return
        q = _qp()
        flag = False
        if q:
            v = q.get("autologin")
            if isinstance(v, list):
                flag = ("1" in v) or (True in v)
            elif isinstance(v, str):
                flag = (v.lower() in ("1","true","yes"))
            elif v is True:
                flag = True
        if not flag or not AUTOLOGIN_TOKEN:
            st.session_state["_autologin_done"] = True
            return
        try:
            data = req(
                "POST", "/auth/magic_login",
                json_data={"token": AUTOLOGIN_TOKEN, "email": email},
                auth=False, timeout=(5, 20), retries=0
            )
            st.session_state["token"] = data.get("access_token")
            st.session_state["me"] = req("GET", "/me", auth=True, timeout=(5, 20))
            st.session_state["_autologin_done"] = True
            st.success("自動ログインしました")
        except Exception as e:
            st.session_state["_autologin_done"] = True
            st.info(f"自動ログイン失敗: {e}")

    try_autologin_once()

    cA, cB = st.columns(2)
    if cA.button("ログイン"):
        ok = False
        data = None
        try:
            data = req(
                "POST", "/login",
                json_data={"email": email, "password": password},
                auth=False, timeout=(10, 80), retries=0
            )
            ok = True
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                tok = (os.getenv("AUTOLOGIN_TOKEN") or os.getenv("ADMIN_TOKEN") or "").strip()
                if tok:
                    try:
                        data = req(
                            "POST", "/auth/magic_login",
                            json_data={"token": tok},
                            auth=False, timeout=(5, 20), retries=0
                        )
                        ok = True
                    except requests.HTTPError as ee:
                        stt = getattr(getattr(ee, "response", None), "status_code", None)
                        if stt in (400, 422):
                            try:
                                data = req(
                                    "POST", "/auth/magic_login",
                                    json_data={"token": tok, "email": email},
                                    auth=False, timeout=(5, 20), retries=0
                                )
                                ok = True
                            except Exception as e3:
                                st.error(f"magic_login 失敗: {e3}")
                        else:
                            msg = getattr(getattr(ee, "response", None), "text", "") or str(ee)
                            st.error(f"magic_login 拒否（{stt}）。AUTOLOGIN_TOKEN が API と合っていません。詳細: {msg[:300]}")
                    except Exception as e2:
                        st.error(f"magic_login 実行エラー: {e2}")
                else:
                    st.error("認証失敗（401/403）。AUTOLOGIN_TOKEN が未設定です。/login 用のメール・パスワードを確認するか、正しいトークンを設定してください。")
            else:
                body = getattr(getattr(e, "response", None), "text", "") or str(e)
                st.error(f"/login 失敗: {body[:300]}")
        except requests.ReadTimeout:
            st.error("ログインでタイムアウト。少し待って再実行してください。")
        except Exception as e:
            st.error(f"ログイン失敗: {e}")
            st.code(traceback.format_exc())

        if ok and data:
            st.session_state["token"] = data.get("access_token")
            try:
                st.session_state["me"] = req("GET", "/me", auth=True, timeout=(5, 30))
                st.success(f"ログイン成功: {st.session_state['me'].get('email','')}")
            except Exception as e:
                st.session_state["me"] = None
                st.warning(f"トークン取得は成功しましたが /me に失敗: {e}")
        else:
            st.info("ログインは完了しませんでした。エラーメッセージを確認してください。")

    if cB.button("ログアウト"):
        for k in ("token","me","_autologin_done"):
            st.session_state[k] = None if k != "_autologin_done" else True
        st.info("ログアウトしました")
        try: st.cache_data.clear()
        except Exception: pass
        try: st.cache_resource.clear()
        except Exception: pass
        st.rerun()

    st.divider()
    st.subheader("メンテナンス")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("🔄 Rerun（再実行）", use_container_width=True):
            st.rerun()
    with col_r2:
        if st.button("🧹 キャッシュ全消去 → 再実行", use_container_width=True):
            try: st.cache_data.clear()
            except Exception: pass
            try: st.cache_resource.clear()
            except Exception: pass
            st.rerun()

    # 診断はデフォルト閉じる（ログの羅列で画面が荒れないように）
    with st.expander("診断 / 完全ログ（SHAP・Models）", expanded=False):
        try:
            qp_dump = dict(_qp())
        except Exception:
            qp_dump = {}
        st.caption("■ Query Params"); st.json(qp_dump)
        st.caption("■ 現在の上書き値（Session）")
        st.write({
            "shap_summary_override": st.session_state.get("shap_summary_override"),
            "shap_models_override":  st.session_state.get("shap_models_override"),
            "env.SHAP_SUMMARY_PATH_HINT": os.getenv("SHAP_SUMMARY_PATH_HINT"),
            "env.SHAP_MODELS_PATH_HINT":  os.getenv("SHAP_MODELS_PATH_HINT"),
        })
        st.text_input("SHAP API パス上書き", key="shap_summary_override",
                      placeholder="/explain/global_importance")
        st.text_input("Models API パス上書き", key="shap_models_override",
                      placeholder="/models")
        if st.button("上書きを適用（再描画）", key="btn_apply_shap_override"):
            try: st.cache_data.clear()
            except Exception: pass
            try: st.cache_resource.clear()
            except Exception: pass
            st.toast("上書きを反映しました。再描画します。", icon="✅")
            st.rerun()

    st.subheader("Health / Ping")
    c1, c2 = st.columns(2)
    if c1.button("Health"):
        try:
            st.json(req("GET","/health", auth=False, timeout=10))
        except Exception as e:
            st.error(e)
    if c2.button("Ping"):
        try:
            st.json(req("GET","/api/predict/ping", auth=False, timeout=10))
        except Exception as e:
            st.error(e)

    st.divider()
    st.subheader("オーナー / 設定")

    owners, owners_src = safe_owners(API)
    if owners:
        default_owner = "学也H" if "学也H" in owners else owners[0]
        try:
            idx = owners.index(default_owner)
        except ValueError:
            idx = 0
        owner = st.selectbox("オーナー", owners, index=idx, key="owner_select")
    else:
        st.warning("オーナー一覧が取得できませんでした。手入力で指定してください。")
        owner = st.text_input("オーナー（手入力）", value=(st.session_state.get("owner_pick") or ""))

    st.session_state["owner_pick"] = (owner or "").strip()
    st.caption(f"owners src: {owners_src}")

    if SHOW_WEBHOOK_UI:
        st.divider()
        st.subheader("通知（Webhook）")
        st.checkbox("Webhook通知を有効化", key="notify_enable",
                    value=st.session_state.get("notify_enable", False))
        st.text_input("Webhook URL", key="notify_webhook_url",
                      placeholder="https://discord.com/api/webhooks/....")
        st.text_input("通知タイトル", key="notify_title", placeholder="VolAI 強シグナル")

        if st.button("テスト通知を送信", key="btn_notify_test"):
            try:
                def _send_webhook(url, title, text):
                    payload = {"text": f"*{title}*\n{text}",
                               "content": f"**{title}**\n{text}"}
                    r = requests.post(url, json=payload, timeout=5)
                    r.raise_for_status()
                url = st.session_state.get("notify_webhook_url") or ""
                if url:
                    _send_webhook(url, st.session_state.get("notify_title") or "VolAI 強シグナル", "通知テスト（接続確認）")
                    st.success("Webhookに送信しました ✅")
                else:
                    st.warning("Webhook URL を入力してください")
            except Exception as e:
                st.error(f"送信失敗: {e}")

# =========================
# 実行前 UI（フィルタ）＋ 自動更新UI
# =========================
st.markdown("---")
st.subheader("フィルタ & しきい値（選ぶだけで即反映・APIは呼びません）")

r1c1, r1c2, r1c3, r1c4 = st.columns([1.1, 1.3, 1.1, 0.8])
with r1c1:
    target_date = st.date_input("対象日（ET）", value=None, key="target_date")
with r1c2:
    band = st.selectbox("時間帯（ETプリセット）",
        ["プレ（04:30–09:30 ET）","レギュラーam（09:30–12:00 ET）","レギュラーpm（12:00–16:00 ET）",
         "アフター（16:00–20:00 ET）","拡張（04:30–20:00 ET）","手入力"], index=4, key="band")
with r1c3:
    tz_name = st.selectbox("時刻フィルタのタイムゾーン", ["America/Toronto","UTC"], index=0, key="tz_name")
with r1c4:
    n = st.slider("取得件数 n", 10, 500, st.session_state.get("n", 200), step=10, key="n")

st.checkbox("差分ハイライト（自動更新時）", key="diff_on",
            value=st.session_state.get("diff_on", True))
st.checkbox("アラートはウォッチのみ", key="alert_only_watchlist",
            value=st.session_state.get("alert_only_watchlist", False))

auto_c1, auto_c2, auto_c3 = st.columns([1.1, 1.1, 1.8])
with auto_c1:
    st.checkbox("自動更新", key="auto_refresh_on",
                value=st.session_state.get("auto_refresh_on", False))
with auto_c2:
    st.number_input("間隔（秒）", min_value=10, max_value=300, step=5, key="auto_refresh_sec",
                    value=st.session_state.get("auto_refresh_sec", 60))
with auto_c3:
    st.checkbox("ライブ優先（0件ならスナップ）", key="auto_refresh_live_first",
                value=st.session_state.get("auto_refresh_live_first", True))

if st.session_state.get("auto_refresh_on"):
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=max(10, int(st.session_state.get("auto_refresh_sec", 60))) * 1000,
                       key="auto_refresh_tick")
    except Exception:
        st.caption("※ 自動更新には `pip install streamlit-autorefresh` が必要です。")

r_time_a, r_time_b = st.columns(2)
with r_time_a:
    manual_start = st.time_input("開始（ET・手入力時のみ）", value=time(4,30), step=300, key="manual_start")
with r_time_b:
    manual_end   = st.time_input("終了（ET・手入力時のみ）", value=time(20,0), step=300, key="manual_end")
if st.session_state["band"] != "手入力":
    manual_start = None
    manual_end   = None

st.markdown("---")
sectors_default = ["Tech","Energy","Healthcare","Utilities","Financials","Industrials","Materials",
                   "RealEstate","Communication","Staples","Discretionary","Consumer"]
s1, s2 = st.columns(2)
with s1:
    sectors = st.multiselect("セクター（未選択＝全件）", sectors_default, default=[], key="sectors")
with s2:
    sizes = st.multiselect("サイズ（未選択＝全件）", ["Large","Mid","Small","Penny"], key="ui_sizes")

wl_c1, wl_c2, wl_c3 = st.columns([2, 1, 1])
with wl_c1:
    st.text_input("ウォッチリスト（カンマ区切り）", key="watchlist_str",
                  placeholder="AAPL, TSLA, NVDA")
with wl_c2:
    st.checkbox("ウォッチのみ", key="watchlist_only",
                value=st.session_state.get("watchlist_only", False))
with wl_c3:
    st.checkbox("先頭に固定", key="watchlist_pin_top",
                value=st.session_state.get("watchlist_pin_top", True))

prev_sig = st.session_state.get("last_sizes_for_ranges", tuple())
cur_sig  = tuple(sorted(st.session_state.get("ui_sizes", [])))

c_toggle, c_reset = st.columns([2,1])
with c_toggle:
    st.checkbox("サイズ選択に合わせて値レンジを自動更新", value=True, key="auto_fill_ranges")
with c_reset:
    if st.button("値レンジをリセット", key="reset_ranges"):
        st.session_state["price_min_in"] = 0.0
        st.session_state["price_max_in"] = 0.0
        st.session_state["mkt_min_in"]   = 0.0
        st.session_state["mkt_max_in"]   = 0.0

def union_ranges_for_sizes(selected: List[str]) -> Tuple[float,float,float,float]:
    SUGGESTED_RANGES = {
        "Large": {"price_min":10.0,"price_max":1000.0,"mkt_min":10_000_000_000.0,"mkt_max":2_000_000_000_000.0},
        "Mid":   {"price_min": 5.0,"price_max": 500.0,"mkt_min": 2_000_000_000.0,"mkt_max":100_000_000_000.0},
        "Small": {"price_min": 1.0,"price_max":  50.0,"mkt_min":   300_000_000.0,"mkt_max":  2_000_000_000.0},
        "Penny": {"price_min": 0.0,"price_max":   5.0,"mkt_min":             0.0,"mkt_max":    500_000_000.0},
    }
    vals = [SUGGESTED_RANGES[s] for s in selected if s in SUGGESTED_RANGES]
    if not vals: return (0.0,0.0,0.0,0.0)
    return (min(v["price_min"] for v in vals),
            max(v["price_max"] for v in vals),
            min(v["mkt_min"]   for v in vals),
            max(v["mkt_max"]   for v in vals))

if (cur_sig != prev_sig) and st.session_state.get("auto_fill_ranges", True):
    st.session_state["last_sizes_for_ranges"] = cur_sig
    pmin, pmax, mmin, mmax = union_ranges_for_sizes(list(cur_sig))
    st.session_state["price_min_in"] = float(pmin)
    st.session_state["price_max_in"] = float(pmax)
    st.session_state["mkt_min_in"]   = float(mmin)
    st.session_state["mkt_max_in"]   = float(mmax)

cA, cB = st.columns(2)
with cA:
    st.number_input("価格 最小USD（任意）", min_value=0.0, step=0.1, format="%.2f",
                    key="price_min_in", value=st.session_state["price_min_in"])
    st.number_input("価格 最大USD（任意）", min_value=0.0, step=0.1, format="%.2f",
                    key="price_max_in", value=st.session_state["price_max_in"])
with cB:
    st.number_input("時価総額 最小USD（任意）", min_value=0.0, step=1e8, format="%.0f",
                    key="mkt_min_in", value=st.session_state["mkt_min_in"])
    st.number_input("時価総額 最大USD（任意）", min_value=0.0, step=1e8, format="%.0f",
                    key="mkt_max_in", value=st.session_state["mkt_max_in"])

# =========================
# 実行（最新：ライブ／スナップ）— 日本語・色分け・上下表示
# =========================
st.markdown("---")
st.subheader("最新予測（予想 → ライブ）")

run_clicked = st.button("実行", use_container_width=True)
auto_tick = st.session_state.get("auto_refresh_on", False) and st.session_state.get("auto_refresh_tick", None) is not None
should_run = run_clicked or auto_tick

if should_run:
    df_live, err_live = fetch_latest(int(st.session_state.get("n", 200)), mode_live=True)
    df_snap, err_snap = fetch_latest(int(st.session_state.get("n", 200)), mode_live=False)
    if err_live: st.warning(f"Live取得で警告: {err_live}")
    if err_snap: st.warning(f"Snap取得で警告: {err_snap}")
    st.session_state["live_raw"] = df_live
    st.session_state["snap_raw"] = df_snap

# --- フィルタ関数（未定義ならここで定義。既に上で定義済みならこの4関数は削除OK） ---
def filter_by_date_time_et(df: pd.DataFrame,
                           target_date_et: Optional[date],
                           band_label: str,
                           manual_start: Optional[time],
                           manual_end: Optional[time],
                           tz_name: str = "America/Toronto") -> pd.DataFrame:
    if df.empty or "_ts_utc" not in df.columns: return df.copy()
    tz_window = ZoneInfo(tz_name)
    tz_et     = ZoneInfo("America/Toronto")
    s = df["_ts_utc"]
    if s.isna().all(): return df.copy()
    presets = {
        "プレ（04:30–09:30 ET）": (time(4,30),  time(9,30)),
        "レギュラーam（09:30–12:00 ET）": (time(9,30), time(12,0)),
        "レギュラーpm（12:00–16:00 ET）": (time(12,0), time(16,0)),
        "アフター（16:00–20:00 ET）": (time(16,0), time(20,0)),
        "拡張（04:30–20:00 ET）": (time(4,30),  time(20,0)),
        "手入力": (manual_start, manual_end),
    }
    if band_label not in presets: return df.copy()
    s_et, e_et = presets[band_label]
    if not (s_et and e_et): return df.copy()
    if target_date_et is None:
        target_date_et = datetime.now(tz_et).date()
    def _mask_for(date_et: date, series_utc: pd.Series) -> pd.Series:
        start_local = datetime.combine(date_et, s_et, tzinfo=tz_window)
        end_local   = datetime.combine(date_et, e_et, tzinfo=tz_window)
        start_utc   = start_local.astimezone(ZoneInfo("UTC"))
        end_utc     = end_local.astimezone(ZoneInfo("UTC"))
        inclusive_end = band_label in ("アフター（16:00–20:00 ET）", "拡張（04:30–20:00 ET）")
        return (series_utc >= start_utc) & ((series_utc <= end_utc) if inclusive_end else (series_utc < end_utc))
    mask = _mask_for(target_date_et, s)
    if int(mask.sum()) > 0: return df[mask].copy()
    try:
        latest_et_date = s.dt.tz_convert(tz_et).dt.date.max()
        if latest_et_date and latest_et_date != target_date_et:
            mask2 = _mask_for(latest_et_date, s)
            if int(mask2.sum()) > 0: return df[mask2].copy()
    except Exception:
        pass
    try:
        offset = -tz_et.utcoffset(datetime.combine(target_date_et, time(12,0))).total_seconds()
        s_shifted = s + timedelta(seconds=offset)
        mask3 = _mask_for(target_date_et, s_shifted)
        if int(mask3.sum()) > 0:
            out = df.copy()
            out["_ts_utc"] = s_shifted
            out["_ts_et"]  = out["_ts_utc"].dt.tz_convert(tz_et)
            out["_date_et"] = out["_ts_et"].dt.date
            out["_time_et"] = out["_ts_et"].dt.strftime("%H:%M")
            return out[mask3].copy()
    except Exception:
        pass
    return df[mask].copy()

def filter_by_sector_size(df: pd.DataFrame, sectors: List[str], sizes: List[str]) -> pd.DataFrame:
    out = df.copy()
    if "sector" in out.columns and sectors: out = out[out["sector"].isin(sectors)]
    if "size" in out.columns and sizes:     out = out[out["size"].isin(sizes)]
    return out

def filter_by_ranges(df: pd.DataFrame,
                     price_min: Optional[float], price_max: Optional[float],
                     mkt_min: Optional[float], mkt_max: Optional[float]) -> Tuple[pd.DataFrame, List[str]]:
    out = df.copy(); notes: List[str] = []
    if "price" in out.columns:
        if price_min is not None: out = out[out["price"] >= price_min]
        if price_max is not None and price_max > 0: out = out[out["price"] <= price_max]
    else:
        if price_min is not None or (price_max is not None and price_max > 0): notes.append("price列が無いため価格レンジは無視しました。")
    if "market_cap" in out.columns:
        if mkt_min is not None: out = out[out["market_cap"] >= mkt_min]
        if mkt_max is not None and mkt_max > 0: out = out[out["market_cap"] <= mkt_max]
    else:
        if mkt_min is not None or (mkt_max is not None and mkt_max > 0): notes.append("market_cap列が無いため時価総額レンジは無視しました。")
    return out, notes

def _apply_filters_common(df_base: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    df = df_base.copy()
    df = filter_by_date_time_et(
        df,
        resolve_target_date_for_filter(st.session_state.get("target_date"), df),
        st.session_state.get("band"),
        st.session_state.get("manual_start"),
        st.session_state.get("manual_end"),
        st.session_state.get("tz_name","America/Toronto"),
    )
    df = filter_by_sector_size(df, st.session_state.get("sectors", []), st.session_state.get("ui_sizes", []))
    df, notes = filter_by_ranges(
        df,
        st.session_state.get("price_min_in"), st.session_state.get("price_max_in"),
        st.session_state.get("mkt_min_in"),   st.session_state.get("mkt_max_in"),
    )
    if "_ts_utc" in df.columns:
        df = df.sort_values("_ts_utc", ascending=False)
    return df, notes

# —— 予想（スナップ） —— #
st.markdown("### 予想（スナップ）")
base = st.session_state.get("snap_raw", pd.DataFrame())
if base is None or base.empty:
    st.info("スナップは0件でした。")
else:
    df_f, notes = _apply_filters_common(base)
    st.caption(f"{len(df_f)}/{len(base)} 行（フィルタ後）" + (" ｜ " + " / ".join(notes) if notes else ""))
    st.dataframe(_to_jp_table(df_f), use_container_width=True)

# —— ライブ最新 —— #
st.markdown("### ライブ最新")
base = st.session_state.get("live_raw", pd.DataFrame())
if base is None or base.empty:
    st.info("ライブは0件でした。")
else:
    df_f, notes = _apply_filters_common(base)
    st.caption(f"{len(df_f)}/{len(base)} 行（フィルタ後）" + (" ｜ " + " / ".join(notes) if notes else ""))
    st.dataframe(_to_jp_table(df_f), use_container_width=True)
          


# =========================
# ログ・サマリー（参考・ヒートマップ） — 先頭に配置／日本語表
# =========================
st.markdown("---")
st.subheader("ログ・サマリー（参考・ヒートマップ）")

# 期間プリセット＋手入力
def _week_monday(date_et: date) -> date: return date_et - timedelta(days=date_et.weekday())
def _week_sunday(date_et: date) -> date: return _week_monday(date_et) + timedelta(days=6)
def _month_first(date_et: date) -> date: return date_et.replace(day=1)
def _month_last(date_et: date) -> date:
    if date_et.month == 12:
        nxt = date_et.replace(year=date_et.year+1, month=1, day=1)
    else:
        nxt = date_et.replace(month=date_et.month+1, day=1)
    return nxt - timedelta(days=1)

col_sumA, col_sumB, col_sumC = st.columns([1.2, 1.3, 1.0])
with col_sumA:
    use_client_agg = st.checkbox("APIを使わずログから集計する", value=False,
                                 help="ONで /predict/logs/summary を使わず、/predict/logs を取得してUI側で集計。")
with col_sumB:
    sum_limit = st.number_input("サマリー集計に使うログ上限", min_value=100, max_value=10000, value=2000, step=100)
with col_sumC:
    apply_owner_in_summary = st.checkbox("サマリーにもオーナーを適用", value=False)

preset = st.radio(
    "期間プリセット",
    options=["今日", "週末締めの一週間（今週）", "月末締めの一か月（今月）", "手入力（カスタム）"],
    horizontal=True, index=0,
    help="週末＝日曜締め、月末＝カレンダー月の末日"
)

tz_et = ZoneInfo("America/Toronto")
_now_et = datetime.now(tz_et)
today_et = _now_et.date()
tz_offset_min = int((_now_et.utcoffset() or timedelta()).total_seconds() // 60)  # 例: 夏時間は -240

custom_c1, custom_c2 = st.columns(2)
start_d_user = end_d_user = None
if preset == "手入力（カスタム）":
    with custom_c1:
        start_d_user = st.date_input("開始日（ET）", value=today_et)
    with custom_c2:
        end_d_user   = st.date_input("終了日（ET）", value=today_et)

if preset == "今日":
    start_d, end_d = today_et, today_et
elif preset == "週末締めの一週間（今週）":
    start_d, end_d = _week_monday(today_et), _week_sunday(today_et)
elif preset == "月末締めの一か月（今月）":
    start_d, end_d = _month_first(today_et), _month_last(today_et)
else:
    start_d = start_d_user or today_et
    end_d   = end_d_user   or today_et
if start_d > end_d:
    start_d, end_d = end_d, start_d

params_summary = {
    "owner": (st.session_state.get("owner_pick") or "").strip() or None if apply_owner_in_summary else None,
    "tz_offset": tz_offset_min,
    "time_start": "04:30",
    "time_end":   "20:00",
    "start": start_d.isoformat(),
    "end":   end_d.isoformat(),
    "limit": int(sum_limit),
}

if use_client_agg:
    df_sum, src_sum = build_summary_fallback_from_logs(params_summary)
else:
    df_sum, src_sum = fetch_logs_summary_api(params_summary)
    if df_sum.empty:
        df_sum, src_sum = build_summary_fallback_from_logs(params_summary)

st.caption(f"summary source: {src_sum} ｜ 期間: {start_d} 〜 {end_d}（ET）")
if df_sum is not None and not df_sum.empty:
    st.dataframe(_to_jp_summary_table(df_sum), use_container_width=True)
    if alt is not None and {"date_et","time_band","avg_pred_vol"}.issubset(df_sum.columns):
        chart = alt.Chart(df_sum).mark_rect().encode(
            x=alt.X('time_band:N', sort=None),
            y=alt.Y('date_et:O', sort='-x'),
            tooltip=['date_et','time_band','avg_pred_vol','avg_fake_rate','avg_confidence'],
            color='avg_pred_vol:Q',
        ).properties(width='container', height=300)
        st.altair_chart(chart, use_container_width=True)
else:
    st.info("サマリーは取得できませんでした。")

# =========================
# ログ一覧（確認用） — 日本語表
# =========================
st.markdown("---")
st.subheader("ログ一覧（確認用）")

log_c1, log_c2 = st.columns([1.0, 1.0])
with log_c1:
    logs_limit = st.number_input("ログ取得上限", min_value=100, max_value=5000, value=2000, step=100)
with log_c2:
    inc_owner = st.checkbox("オーナーで絞り込み", value=True)

if st.button("ログを取得"):
    df_logs = fetch_logs(limit=int(logs_limit), owner=(st.session_state.get("owner_pick") if inc_owner else None))
    st.session_state["logs_cached_df"] = df_logs

df_logs_show = st.session_state.get("logs_cached_df", pd.DataFrame())
if df_logs_show is not None and not df_logs_show.empty:
    st.caption(f"endpoint: {st.session_state.get('_logs_endpoint_used','')}")
    # ここを日本語化して表示
    st.dataframe(_to_jp_table(df_logs_show), use_container_width=True)
else:
    st.info("まだログを取得していません（または0件）。『ログを取得』を押してください。")

# =========================
# SHAP サマリー（グローバル重要度） — 最後に配置／日本語表
# =========================
st.markdown("---")
st.subheader("SHAP サマリー（グローバル重要度）")

models, models_src = fetch_models_list()
lc, rc = st.columns([2, 1])

with lc:
    if models:
        idx0 = 0
        if st.session_state.get("shap_model_pick") in models:
            idx0 = models.index(st.session_state["shap_model_pick"])
        pick = st.selectbox("モデル選択", options=models, index=idx0, key="shap_model_pick")
    else:
        st.info("モデル一覧が取得できなかったため、手入力で指定してください。")
        pick = st.text_input("モデル名（手入力）", key="shap_model_pick", placeholder="例）best, prod, v1.2 など")

with rc:
    topk = st.number_input("Top-K", 1, 200, value=int(st.session_state.get("shap_topk", 30)), key="shap_topk")

_owner_for_shap = (st.session_state.get("owner_pick") or "").strip() or None

col_btn1, col_btn2, col_btn3 = st.columns([1.2, 1.0, 1.0])
with col_btn1:
    if st.button("SHAP を取得", key="btn_fetch_shap"):
        if not (pick or "").strip():
            st.warning("モデル名を入力または選択してください。")
        else:
            df_shap, shap_src = fetch_shap_summary_api(
                model=str(pick).strip(), owner=_owner_for_shap, topk=int(topk)
            )
            st.session_state["shap_summary_src"] = shap_src
            if df_shap.empty:
                st.warning("SHAP サマリーは0行でした。パス上書きまたはファイルアップロードを試してください。")
            else:
                st.session_state["shap_summary_df"] = df_shap
                st.success(f"{len(df_shap)} 行を取得: {shap_src}")

with col_btn2:
    if st.button("CSV として保存", key="btn_shap_save_csv"):
        df = st.session_state.get("shap_summary_df", pd.DataFrame())
        if df is None or df.empty:
            st.info("SHAP データがありません。先に取得するか、ファイルをアップロードしてください。")
        else:
            csv = normalize_shap_summary(df).to_csv(index=False).encode("utf-8")
            st.download_button("ダウンロード: shap_summary.csv", data=csv, file_name="shap_summary.csv", mime="text/csv")

with col_btn3:
    if st.button("Excel として保存", key="btn_shap_save_xlsx"):
        df = st.session_state.get("shap_summary_df", pd.DataFrame())
        if df is None or df.empty:
            st.info("SHAP データがありません。先に取得するか、ファイルをアップロードしてください。")
        else:
            try:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as w:
                    normalize_shap_summary(df).to_excel(w, index=False, sheet_name="shap_summary")
                buf.seek(0)
                st.download_button("ダウンロード: shap_summary.xlsx", data=buf.getvalue(),
                                   file_name="shap_summary.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except Exception as e:
                st.error(f"Excel 書き出しに失敗: {e}")

up = st.file_uploader("SHAP サマリー（CSV/JSON/TSV）をアップロード（APIが無い場合の代替）",
                      type=["csv","json","tsv"])
if up is not None:
    try:
        if up.name.lower().endswith(".json"):
            raw = json.loads(up.read().decode("utf-8", errors="ignore"))
            rows = _extract_list_like_any(raw)
            df_up = normalize_shap_summary(pd.DataFrame(rows))
        else:
            sep = "\t" if up.name.lower().endswith(".tsv") else ","
            df_up = pd.read_csv(up, sep=sep)
            df_up = normalize_shap_summary(df_up)
        if not df_up.empty:
            st.session_state["shap_summary_df"] = df_up
            st.session_state["shap_summary_src"] = "upload"
            st.success(f"アップロードから {len(df_up)} 行を読み込みました。")
        else:
            st.warning("アップロード内容から有効な行が見つかりませんでした。")
    except Exception as e:
        st.error(f"読み込みに失敗しました: {e}")

df_shap_show = st.session_state.get("shap_summary_df", pd.DataFrame())
if df_shap_show is not None and not df_shap_show.empty:
    st.caption(f"source: {st.session_state.get('shap_summary_src','')}")
    st.dataframe(_to_jp_shap_table(df_shap_show), use_container_width=True)