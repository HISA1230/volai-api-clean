# streamlit_app.py — Volatility AI Minimal UI
# (single colored table per section, AIコメントのみ、fake-rate low=green)

from __future__ import annotations

import os, json, traceback, importlib, base64, io
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, Tuple, Optional, List, TYPE_CHECKING

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ------------ requests session ------------
_session: Optional[requests.Session] = None
def get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retries = Retry(
            total=2, connect=2, read=2,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD","GET","POST","PUT","DELETE","OPTIONS","PATCH"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        s.mount("https://", adapter); s.mount("http://", adapter)
        _session = s
    return _session

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
load_dotenv()
SHOW_WEBHOOK_UI = os.getenv("SHOW_WEBHOOK_UI", "1").lower() not in ("0","false","no","off")
st.set_page_config(page_title="Volatility AI UI", layout="wide")


def get_query_params():
    try:
        return st.query_params
    except Exception:
        return st.experimental_get_query_params()

def get_api_base() -> str:
    q = get_query_params()
    if q and ("api" in q) and q["api"]:
        val = q["api"][0] if isinstance(q["api"], list) else q["api"]
        return val.strip().rstrip("/")
    env = os.getenv("API_BASE", "").strip().rstrip("/")
    return env if env else "http://127.0.0.1:8000"

API = get_api_base()
def autologin_if_needed():
    if st.session_state.get("token"):
        return
    q = get_query_params()
    want = (os.getenv("AUTOLOGIN", "0").lower() not in ("0","false","no","off")) \
           or (str(q.get("autologin", "")).lower() in ("1","true","yes"))
    if not want:
        return
    email = os.getenv("AUTOLOGIN_EMAIL", os.getenv("API_EMAIL", "test@example.com"))
    password = os.getenv("AUTOLOGIN_PASSWORD", os.getenv("API_PASSWORD", "test1234"))
    try:
        try:
            _ = req("GET","/health", auth=False, timeout=(5,10), retries=1)
        except Exception:
            pass
        data = req("POST","/login", {"email":email,"password":password}, auth=False, timeout=(10,80), retries=1)
        st.session_state["token"] = data.get("access_token")
        st.session_state["me"] = req("GET","/me", auth=True, timeout=(5,30))
        st.toast(f"自動ログイン: {st.session_state['me'].get('email','')}", icon="✅")
    except Exception as e:
        st.warning(f"自動ログイン失敗: {e}")

    autologin_if_needed()

# ========== Settings: save/load helpers ==========
SETTINGS_KEYS = [
    # UI filters
    "target_date","band","tz_name","n","sectors","ui_sizes",
    "price_min_in","price_max_in","mkt_min_in","mkt_max_in",
    # thresholds
    "pv_y","pv_r","fr_o","fr_r","cf_a","cf_h",
    "th_preset",
    # display toggles
    "show_symbols","use_badges",
    # watchlist
    "watchlist_str","watchlist_only","watchlist_pin_top","alert_only_watchlist",
    # owner
    "owner_pick",
    # notifications
    "notify_webhook_url","notify_enable","notify_title",    
]

def collect_settings() -> Dict[str, Any]:
    d = {}
    for k in SETTINGS_KEYS:
        d[k] = st.session_state.get(k)
    if isinstance(d.get("target_date"), (datetime, date)):
        d["target_date"] = d["target_date"].isoformat()
    return d

def apply_settings(cfg: Dict[str, Any]) -> None:
    for k in SETTINGS_KEYS:
        if k in cfg:
            st.session_state[k] = cfg[k]
    td = st.session_state.get("target_date")
    if isinstance(td, str) and td:
        try:
            st.session_state["target_date"] = date.fromisoformat(td)
        except Exception:
            pass
    # 可能ならプリセット名も再適用（日本語→英語キー正規化）
    tp_raw = cfg.get("th_preset")
    tp = normalize_preset_name(tp_raw)
    if isinstance(tp, str) and tp in PRESETS:
        apply_threshold_preset(tp)
        st.session_state["th_preset"] = tp
        st.session_state["_applied_preset"] = tp  # UI同期

def _b64_encode(d: Dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, ensure_ascii=False).encode("utf-8")).decode("utf-8")

def _b64_decode(s: str) -> Dict[str, Any]:
    s = s.strip()
    s += "=" * (-len(s) % 4)  # パディング補完
    return json.loads(base64.urlsafe_b64decode(s.encode("utf-8")))

# --- JSON/URL 以外の小ヘルパー ---
def _to_json_bytes(d: Dict[str, Any]) -> bytes:
    return json.dumps(d, ensure_ascii=False, indent=2).encode("utf-8")

def parse_watchlist(s: Optional[str]) -> set:
    """カンマ区切りの銘柄文字列を set(大文字) に。全角カンマ対応。"""
    if not isinstance(s, str): return set()
    parts = [x.strip().upper() for x in s.replace("，", ",").split(",")]
    return {p for p in parts if p}

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

def req(method: str, path: str, json_data=None, auth=False, timeout=30, retries: int=0):
    url = f"{API}{path}"
    headers = {"Content-Type":"application/json"}
    if auth and st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state['token']}"
    s = get_session()
    for attempt in range(retries+1):
        try:
            r = s.request(method, url, headers=headers, json=json_data, timeout=timeout)
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            return r.json() if ctype.startswith("application/json") else r.text
        except (requests.ReadTimeout, requests.ConnectTimeout):
            if attempt < retries:
                import time as _t; _t.sleep(0.7*(2**attempt)); continue
            raise
        except Exception:
            raise

# ---- ISO / epoch 自動判定
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
st.session_state.setdefault("debug_timefix", {})  # 補正状況

st.session_state.setdefault("notify_webhook_url", "")
st.session_state.setdefault("notify_enable", False)
st.session_state.setdefault("notify_title", "VolAI 強シグナル")
# 重複通知防止（今セッション内）
st.session_state.setdefault("notified_keys_snap", set())
st.session_state.setdefault("notified_keys_live", set())

# ---- URLからの自動復元（初回のみ）
if not st.session_state.get("loaded_from_url", False):
    q = get_query_params()
    try:
        cfg_b64 = (q.get("cfg") or [""])[0] if q else ""
        if cfg_b64:
            apply_settings(_b64_decode(cfg_b64))
            st.session_state["loaded_from_url"] = True
            st.toast("URLの設定を復元しました", icon="✅")
    except Exception:
        pass

# =========================
# しきい値
# =========================
Thresholds = Dict[str, Dict[str, float]]
PRESETS: Dict[str, Thresholds] = {
    "relaxed":  {"pred_vol":{"yellow":0.008,"red":0.030}, "fake_rate":{"orange":0.30,"red":0.60}, "confidence":{"attention":0.30,"high":0.60}},
    "standard": {"pred_vol":{"yellow":0.012,"red":0.040}, "fake_rate":{"orange":0.25,"red":0.50}, "confidence":{"attention":0.40,"high":0.70}},
    "strict":   {"pred_vol":{"yellow":0.018,"red":0.060}, "fake_rate":{"orange":0.20,"red":0.40}, "confidence":{"attention":0.50,"high":0.80}},
}

# --- 日本語ラベルと正規化 ---
PRESET_LABELS = {"relaxed": "緩め", "standard": "標準", "strict": "厳しめ"}
PRESET_LABELS_INV = {v: k for k, v in PRESET_LABELS.items()}

def normalize_preset_name(x: Optional[str]) -> str:
    if not isinstance(x, str):
        return ""
    x = x.strip()
    if x in PRESETS:
        return x
    # URL/保存から日本語名で来ても受け付ける
    return PRESET_LABELS_INV.get(x, x)

# --- しきい値プリセット：セッション既定 ＋ ヘルパー ---
st.session_state.setdefault("th_preset", "standard")
st.session_state.setdefault("threshold_profiles", {})  # {name: {pv_y, pv_r, fr_o, fr_r, cf_a, cf_h}}

def apply_threshold_preset(preset_name: str) -> None:
    p = PRESETS.get(preset_name)
    if not p:
        return
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
        if k in d:
            st.session_state[k] = float(d[k])

def thresholds_equal_to_preset(name: str, tol: float = 1e-9) -> bool:
    p = PRESETS.get(name)
    if not p:
        return False
    cur = current_thresholds_dict()
    ref = {
        "pv_y": p["pred_vol"]["yellow"],
        "pv_r": p["pred_vol"]["red"],
        "fr_o": p["fake_rate"]["orange"],
        "fr_r": p["fake_rate"]["red"],
        "cf_a": p["confidence"]["attention"],
        "cf_h": p["confidence"]["high"],
    }
    return all(abs(float(cur[k]) - float(ref[k])) <= tol for k in cur)

def to_thresholds_from_session() -> Thresholds:
    return {
        "pred_vol":{"yellow":float(st.session_state["pv_y"]), "red":float(st.session_state["pv_r"])},
        "fake_rate":{"orange":float(st.session_state["fr_o"]), "red":float(st.session_state["fr_r"])},
        "confidence":{"attention":float(st.session_state["cf_a"]), "high":float(st.session_state["cf_h"])},
    }

def _fmt_both(v):
    if pd.isna(v): return ""
    return f"{v:.3f} ({v*100:.1f}%)"

def auto_comment(row: pd.Series, th: Thresholds) -> str:
    pv = row.get("pred_vol"); fr = row.get("fake_rate"); cf = row.get("confidence")
    msg: List[str] = []
    if pd.notna(pv) and pd.notna(cf) and pd.notna(fr):
        if pv >= th["pred_vol"]["red"] and cf >= th["confidence"]["high"] and fr < th["fake_rate"]["orange"]:
            msg.append("高信頼×ボラ大（注目）")
        elif fr >= th["fake_rate"]["red"]:
            msg.append("だまし高（回避）")
        elif cf < th["confidence"]["attention"]:
            msg.append("信頼低")
        elif pv >= th["pred_vol"]["yellow"]:
            msg.append("程よいボラ")
        else:
            msg.append("静穏")
    elif pd.notna(pv):
        if pv >= th["pred_vol"]["red"]: msg.append("ボラ大")
        elif pv >= th["pred_vol"]["yellow"]: msg.append("ボラ中")
        else: msg.append("静穏")
    c_api = row.get("comment")
    if isinstance(c_api, str) and c_api.strip(): msg.append(c_api.strip())
    return " / ".join(msg)
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

def fetch_latest(n: int, mode_live: bool=False) -> Tuple[pd.DataFrame, Optional[str]]:  # noqa: D401
    try:
        path = f"/api/predict/latest?n={n}" + ("&mode=live" if mode_live else "")
        res = req("GET", path, auth=False, timeout=20)
        df = pd.DataFrame(res)
        if df.empty: return df, None
        if "symbols" in df.columns:
            df["symbols"] = df["symbols"].apply(lambda v: ", ".join(v) if isinstance(v,(list,tuple)) else v)
        for c in ("pred_vol","fake_rate","confidence","price","market_cap"):
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
        df = attach_time_columns(df)
        cols = [c for c in ["_ts_utc","ts_utc","_ts_et","_date_et","_time_et","time_band","sector","size",
                            "pred_vol","fake_rate","confidence","rec_action","symbols","comment","price","market_cap","symbol"]
                if c in df.columns]
        return df[cols], None
    except Exception as e:
        return pd.DataFrame(), f"{e}"

def resolve_target_date_for_filter(target_date_et: Optional[date], df_ref: pd.DataFrame) -> Optional[date]:
    if target_date_et is not None: return target_date_et
    try:
        if "_ts_utc" in df_ref.columns and not df_ref["_ts_utc"].isna().all():
            tz = ZoneInfo("America/Toronto")
            return df_ref["_ts_utc"].dt.tz_convert(tz).dt.date.max()
    except Exception:
        pass
    return None

# =========================
# ヘッダ & サイドバー
# =========================
st.title("Volatility AI – Minimal UI")
st.caption(f"API Base: {API} ｜ Swagger: {API}/docs")

with st.sidebar:
    st.subheader("ログイン")
    default_email = os.getenv("API_EMAIL", "test@example.com")
    default_pass  = os.getenv("API_PASSWORD", "test1234")
    email = st.text_input("Email", value=default_email)
    password = st.text_input("Password", type="password", value=default_pass)

    # --- 自動ログイン（?autologin=1 で有効、トークンはUIの環境変数から） ---
    AUTOLOGIN_TOKEN = os.getenv("AUTOLOGIN_TOKEN") or os.getenv("ADMIN_TOKEN")

    def _try_autologin():
        if st.session_state.get("_autologin_done"):
            return
        q = get_query_params()
        # autologin フラグをクエリから判定
        flag = False
        if q:
            val = q.get("autologin")
            if isinstance(val, list):
                flag = ("1" in val) or (True in val)
            elif isinstance(val, str):
                flag = (val == "1")
            elif val is True:
                flag = True
        if not flag or not AUTOLOGIN_TOKEN:
            return
        try:
            # API の /auth/magic_login でトークン発行
            data = req(
                "POST", "/auth/magic_login",
                {"token": AUTOLOGIN_TOKEN, "email": email},
                auth=False, timeout=(5, 20), retries=0
            )
            st.session_state["token"] = data.get("access_token")
            st.session_state["me"] = req("GET", "/me", auth=True, timeout=(5, 20))
            st.session_state["_autologin_done"] = True
            st.success("自動ログインしました")
        except Exception as e:
            st.session_state["_autologin_done"] = True
            st.info(f"自動ログイン失敗: {e}")

    _try_autologin()
    
    cA, cB = st.columns(2)
    if cA.button("ログイン"):
        try:
            try:
                _ = req("GET","/health", auth=False, timeout=(5,10), retries=1)
            except Exception:
                pass
            data = req("POST","/login", {"email":email,"password":password}, auth=False, timeout=(10,80), retries=1)
            st.session_state["token"] = data.get("access_token")
            st.session_state["me"] = req("GET","/me", auth=True, timeout=(5,30))
            st.success(f"ログイン成功: {st.session_state['me'].get('email','')}")
        except requests.ReadTimeout:
            st.error("ログインでタイムアウト。コールドスタートの可能性。少し待ってから再実行してください。")
        except Exception as e:
            st.error(f"ログイン失敗: {e}")
            st.code(traceback.format_exc())

    if cB.button("ログアウト"):
        st.session_state["token"] = None
        st.session_state["me"] = None
        st.info("ログアウトしました")

    st.divider()
    st.subheader("Health / Ping")
    c1, c2 = st.columns(2)
    if c1.button("Health"):
        try: st.json(req("GET","/health", auth=False, timeout=10))
        except Exception as e: st.error(e)
    if c2.button("Ping"):
        try: st.json(req("GET","/api/predict/ping", auth=False, timeout=10))
        except Exception as e: st.error(e)

    st.divider()
    st.subheader("オーナー / 設定")
    default_owners = [x.strip() for x in os.getenv("OWNERS_LIST", "学也,学也H,正恵,正恵M,共用").split(",") if x.strip()]
    owners_selectable = default_owners.copy()
    try:
        owners_available = api_has("/owners") or api_has("/owners/settings")
    except Exception:
        owners_available = False
    if owners_available and st.session_state.get("token"):
        
        try:
            owners_data = req("GET","/owners", auth=True, timeout=(5,20))
            if isinstance(owners_data, list):
                api_names = []
                for item in owners_data:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("owner") or item.get("id")
                        if name: api_names.append(str(name))
                if api_names: owners_selectable = api_names
        except Exception:
            # APIで取れなかった時は黙ってローカル候補にフォールバック
            pass
    else:
        st.caption("※サーバ未実装（または404）。ローカル候補から選択できます。")
    st.session_state["owner_pick"] = st.selectbox("オーナー", owners_selectable, index=0)
    
    # ===== 通知（Webhook）を環境変数で出し分け =====
    if SHOW_WEBHOOK_UI:
        st.divider()
        st.subheader("通知（Webhook）")

        st.checkbox(
            "Webhook通知を有効化",
            key="notify_enable",
            value=st.session_state.get("notify_enable", False)
        )
        st.text_input(
            "Webhook URL",
            key="notify_webhook_url",
            placeholder="https://discord.com/api/webhooks/...."
        )
        st.text_input(
            "通知タイトル",
            key="notify_title",
            placeholder="VolAI 強シグナル"
        )

        # 接続確認
        if st.button("テスト通知を送信", key="btn_notify_test"):
            try:
                def _send_webhook(url, title, text):
                    import requests
                    payload = {
                        # Slack 互換
                        "text": f"*{title}*\n{text}",
                        # Discord など content しか見ない先にも対応
                        "content": f"**{title}**\n{text}",
                    }
                    r = requests.post(url, json=payload, timeout=5)
                    r.raise_for_status()

                url = st.session_state.get("notify_webhook_url") or ""
                if url:
                    _send_webhook(
                        url,
                        st.session_state.get("notify_title") or "VolAI 強シグナル",
                        "通知テスト（接続確認）"
                    )
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

# 自動更新・ウォッチリスト
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

# タイマー駆動
if st.session_state.get("auto_refresh_on"):
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=max(10, int(st.session_state.get("auto_refresh_sec", 60))) * 1000,
                       key="auto_refresh_tick")
    except Exception:
        st.caption("※ 自動更新には `pip install streamlit-autorefresh` が必要です。")

# 手入力の時間UI
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

# ウォッチリスト
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

if (cur_sig != prev_sig) and st.session_state.get("auto_fill_ranges", True):
    st.session_state["last_sizes_for_ranges"] = cur_sig
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

st.markdown("---")
st.caption(
    f"現在値：予測ボラ（黄≥{st.session_state['pv_y']:.3f} / 赤≥{st.session_state['pv_r']:.3f}）｜"
    f"だまし率（橙≥{st.session_state['fr_o']:.2f} / 赤≥{st.session_state['fr_r']:.2f}）｜"
    f"信頼度（注意≥{st.session_state['cf_a']:.2f} / 高信頼≥{st.session_state['cf_h']:.2f}）"
)

# ▼▼ しきい値プリセット（日本語表示・1回で反映） ▼▼
pr_c1, pr_c2, pr_c3, pr_c4 = st.columns([1.3, 1.2, 1.2, 1.8])

with pr_c1:
    _is_rel = thresholds_equal_to_preset("relaxed")
    _is_std = thresholds_equal_to_preset("standard")
    _is_str = thresholds_equal_to_preset("strict")
    if   _is_rel: cur_key = "relaxed"
    elif _is_std: cur_key = "standard"
    elif _is_str: cur_key = "strict"
    else:         cur_key = "(custom)"

    labels = [PRESET_LABELS["relaxed"], PRESET_LABELS["standard"], PRESET_LABELS["strict"], "(カスタム)"]
    key_order = ["relaxed", "standard", "strict", "(custom)"]
    idx = key_order.index(cur_key)

    chosen_label = st.selectbox("しきい値プリセット", options=labels, index=idx, key="th_preset_ui")
    chosen_key = PRESET_LABELS_INV.get(chosen_label, "(custom)")

    if chosen_key in PRESETS and chosen_key != st.session_state.get("_applied_preset"):
        apply_threshold_preset(chosen_key)
        st.session_state["th_preset"] = chosen_key
        st.session_state["_applied_preset"] = chosen_key
        st.toast(f"プリセットを適用: {chosen_label}", icon="✅")
        try:
            st.rerun()
        except Exception:
            pass

with pr_c2:
    th_name = st.text_input("カスタム名", key="th_custom_name", placeholder="例) Penny_低だまし")
    if st.button("カスタム保存", key="btn_th_save"):
        if th_name.strip():
            st.session_state["threshold_profiles"][th_name.strip()] = current_thresholds_dict()
            st.success(f"保存しました：{th_name.strip()}")
        else:
            st.warning("カスタム名を入力してください")

with pr_c3:
    profiles = sorted(st.session_state.get("threshold_profiles", {}).keys())
    pick = st.selectbox("カスタム読込", options=["(選択)"] + profiles, key="th_pick")
    if st.button("読込", key="btn_th_load") and pick and pick != "(選択)":
        load_thresholds_from_dict(st.session_state["threshold_profiles"][pick])
        st.session_state["th_preset"] = "(custom)"
        st.success(f"読込み済み：{pick}")
        try:
            st.rerun()
        except Exception:
            pass

with pr_c4:
    with st.expander("しきい値の詳細（直接編集）", expanded=False):
        e1, e2, e3 = st.columns(3)
        with e1:
            st.number_input("予測ボラ：黄閾値", min_value=0.0, step=0.001, format="%.3f", key="pv_y")
            st.number_input("だまし率：橙閾値", min_value=0.0, step=0.01,  format="%.2f", key="fr_o")
        with e2:
            st.number_input("予測ボラ：赤閾値", min_value=0.0, step=0.001, format="%.3f", key="pv_r")
            st.number_input("だまし率：赤閾値", min_value=0.0, step=0.01,  format="%.2f", key="fr_r")
        with e3:
            st.number_input("信頼度：注意以上", min_value=0.0, step=0.01,  format="%.2f", key="cf_a")
            st.number_input("信頼度：高信頼", min_value=0.0, step=0.01,  format="%.2f", key="cf_h")
        st.caption("※ここで数値を変えるとプリセット表示は自動で「(カスタム)」になります。")

st.caption(
    f"現在値：予測ボラ（黄≥{st.session_state['pv_y']:.3f} / 赤≥{st.session_state['pv_r']:.3f}）｜"
    f"だまし率（橙≥{st.session_state['fr_o']:.2f} / 赤≥{st.session_state['fr_r']:.2f}）｜"
    f"信頼度（注意≥{st.session_state['cf_a']:.2f} / 高信頼≥{st.session_state['cf_h']:.2f}）"
)
show_symbols = st.checkbox("銘柄（symbols）を表示", value=True, key="show_symbols")

# 設定の保存/読込
save_c1, save_c2, save_c3 = st.columns([1.4, 1.2, 2.0])
with save_c1:
    profile_name = st.text_input("設定名", key="profile_name", placeholder="例) Penny_緩め")

with save_c2:
    if st.button("保存", key="btn_save_profile"):
        st.session_state.setdefault("profiles", {})
        st.session_state["profiles"][profile_name or "default"] = collect_settings()
        st.success(f"保存しました：{profile_name or 'default'}")

with save_c3:
    opts = sorted(list(st.session_state.get("profiles", {}).keys()))
    sel = st.selectbox("読込", options=["(選択)"] + opts, key="profile_pick")
    if sel and sel != "(選択)":
        try:
            apply_settings(st.session_state["profiles"][sel])
            st.success(f"読込み済み：{sel}（自動で再描画します）")
            try:
                st.experimental_rerun()
            except Exception:
                st.rerun()
        except Exception as e:
            st.error(f"読込失敗: {e}")
            
# --- 共有URL（?cfg=...）: 保存/読込ブロックの直後〜 実行ボタンの手前に追加 ---
with st.expander("共有URL（?cfg=...）", expanded=False):
    c1, c2 = st.columns([1.2, 2.0])

    with c1:
        st.markdown("**現在の設定 → URL へ反映**")
        if st.button("URLを更新（?cfg=… を付与）", use_container_width=True, key="btn_apply_url_cfg"):
            cfg = collect_settings()               # 現在のUI状態
            token = _b64_encode(cfg)               # Base64(JSON)
            set_query_params_safe(cfg=token)       # クエリを ?cfg=… に置き換え
            st.success("URLを更新しました。ブラウザのアドレスバーのURLをコピーしてください。")
            st.code(f"?cfg={token[:80]}...  (len={len(token)})", language="text")

    with c2:
        st.markdown("**URL / cfgトークンの貼り付け → 適用**")
        pasted = st.text_input("URL または cfg トークンを貼り付け", key="cfg_paste_input",
                               placeholder="https://example.com/?cfg=XXXX...  または  XXXX...")
        ap_col1, ap_col2 = st.columns([1,1])
        with ap_col1:
            if st.button("貼り付け内容を適用", key="btn_import_cfg"):
                import urllib.parse as up
                try:
                    tok = (pasted or "").strip()
                    if not tok:
                        st.warning("URL または cfg トークンを入力してください。")
                    else:
                        # URLからcfg=抽出 or トークンそのまま
                        if tok.lower().startswith(("http://","https://")):
                            qs = up.parse_qs(up.urlparse(tok).query)
                            tok = (qs.get("cfg") or [""])[0]
                        settings = _b64_decode(tok)
                        if not isinstance(settings, dict):
                            raise ValueError("cfg のデコード結果が dict ではありません。")
                        apply_settings(settings)
                        st.success("設定を反映しました（UIを再描画します）")
                        try:
                            st.experimental_rerun()
                        except Exception:
                            st.rerun()
                except Exception as e:
                    st.error(f"適用に失敗しました: {e}")
        with ap_col2:
            if st.button("現在のURLをクリア（?cfg除去）", key="btn_clear_cfg"):
                # 他のクエリを保持したい場合は必要に応じて追加
                set_query_params_safe()  # すべてのクエリを消す
                st.toast("クエリをクリアしました。", icon="✅")
                
run_clicked = st.button("実行", use_container_width=True)

# --- 0件時：①最新ET日に合わせ → ②ET誤解釈(+4/+5h)補正
def filter_by_date_time_et(df: pd.DataFrame,
                           target_date_et: Optional[date],
                           band_label: str,
                           manual_start: Optional[time],
                           manual_end: Optional[time],
                           tz_name: str="America/Toronto") -> pd.DataFrame:
    if df.empty or "_ts_utc" not in df.columns: return df.copy()

    tz_window = ZoneInfo(tz_name)
    tz_et     = ZoneInfo("America/Toronto")
    s = df["_ts_utc"]
    if s.isna().all():
        st.caption("※注意：timestamp が解析できないため時間帯フィルタはスキップしました（全件表示）。")
        return df.copy()

    presets = {
        "プレ（04:30–09:30 ET）": (time(4,30),  time(9,30)),
        "レギュラーam（09:30–12:00 ET）": (time(9,30), time(12,0)),
        "レギュラーpm（12:00–16:00 ET）": (time(12,0), time(16,0)),
        "アフター（16:00–20:00 ET）": (time(16,0), time(20,0)),
        "拡張（04:30–20:00 ET）": (time(4,30),  time(20,0)),
        "手入力": (manual_start, manual_end),
    }
    if band_label not in presets:
        return df.copy()
    s_et, e_et = presets[band_label]
    if not (s_et and e_et):
        return df.copy()

    if target_date_et is None:
        target_date_et = datetime.now(tz_et).date()

    def build_mask(for_date: date, series_utc: pd.Series) -> pd.Series:
        start_local = datetime.combine(for_date, s_et, tzinfo=tz_window)
        end_local   = datetime.combine(for_date, e_et, tzinfo=tz_window)
        start_utc   = start_local.astimezone(ZoneInfo("UTC"))
        end_utc     = end_local.astimezone(ZoneInfo("UTC"))
        inclusive_end = band_label in ("アフター（16:00–20:00 ET）", "拡張（04:30–20:00 ET）")
        return (series_utc >= start_utc) & ((series_utc <= end_utc) if inclusive_end else (series_utc < end_utc))

    mask = build_mask(target_date_et, s)
    hit = int(mask.sum())

    # デバッグ：生データ範囲
    try:
        et_series = s.dt.tz_convert(tz_et)
        st.session_state["debug_timefix"]["raw_min_utc"] = str(pd.to_datetime(s.min())) if len(s)>0 else ""
        st.session_state["debug_timefix"]["raw_max_utc"] = str(pd.to_datetime(s.max())) if len(s)>0 else ""
        st.session_state["debug_timefix"]["raw_min_et"]  = str(pd.to_datetime(et_series.min())) if len(s)>0 else ""
        st.session_state["debug_timefix"]["raw_max_et"]  = str(pd.to_datetime(et_series.max())) if len(s)>0 else ""
    except Exception:
        pass

    if hit == 0:
        try:
            latest_et_date = s.dt.tz_convert(tz_et).dt.date.max()
        except Exception:
            latest_et_date = None
        if latest_et_date and latest_et_date != target_date_et:
            mask_latest = build_mask(latest_et_date, s)
            if int(mask_latest.sum()) > 0:
                st.session_state["debug_timefix"]["date_auto_aligned"] = True
                st.session_state["debug_timefix"]["aligned_date_et"] = str(latest_et_date)
                return df[mask_latest].copy()

    # ② ET誤解釈補正
    offset = -tz_et.utcoffset(datetime.combine(target_date_et, time(12,0))).total_seconds()
    offset = timedelta(seconds=offset)  # EDTなら+4h
    s_shifted = s + offset
    mask2 = build_mask(target_date_et, s_shifted)
    hit2 = int(mask2.sum())

    st.session_state["debug_timefix"]["auto_fix_applied"] = (hit2 > 0)
    st.session_state["debug_timefix"]["hit_before"] = hit
    st.session_state["debug_timefix"]["hit_after"]  = hit2
    st.session_state["debug_timefix"]["offset_hours"] = round(offset.total_seconds()/3600, 2)

    if hit2 > 0:
        st.warning(f"時間帯フィルタ：APIの 'ts_utc' が ET として出力されている可能性があるため +{offset.total_seconds()/3600:.0f} 時間補正を適用しました（{hit2}件ヒット）。")
        out = df.copy()
        out["_ts_utc"] = s_shifted
        out["_ts_et"]  = out["_ts_utc"].dt.tz_convert(ZoneInfo("America/Toronto"))
        out["_date_et"] = out["_ts_et"].dt.date
        out["_time_et"] = out["_ts_et"].dt.strftime("%H:%M")
        return out[mask2].copy()

    return df[mask].copy()

def filter_by_sector_size(df: pd.DataFrame, sectors: List[str], sizes: List[str]) -> pd.DataFrame:
    out = df.copy()
    if "sector" in out.columns and sectors: out = out[out["sector"].isin(sectors)]
    if "size"   in out.columns and sizes:   out = out[out["size"].isin(sizes)]
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

def apply_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    """watchlist_only / pin_top を適用し、_is_watch を付与"""
    if df is None or df.empty:
        return df
    wl = parse_watchlist(st.session_state.get("watchlist_str"))
    if not wl:
        df["_is_watch"] = False
        return df
    def is_watch_row(r: pd.Series) -> bool:
        sym = ""
        if "symbols" in r and isinstance(r["symbols"], str):
            sym = _first_symbol_key(r["symbols"]).upper()
        elif "symbol" in r and isinstance(r["symbol"], str):
            sym = str(r["symbol"]).upper()
        return sym in wl
    flag = df.apply(is_watch_row, axis=1)
    if st.session_state.get("watchlist_only", False):
        df = df[flag].copy()
    elif st.session_state.get("watchlist_pin_top", True):
        df = pd.concat([df[flag], df[~flag]], ignore_index=True)
    df["_is_watch"] = flag.values if len(flag)==len(df) else False
    return df

# ===== 予想時間（買い/売りの目安）を各行に付与 =====
def _first_symbol_key(x) -> str:
    if isinstance(x, str):
        parts = [p.strip() for p in x.split(",") if p.strip()]
        return parts[0] if parts else ""
    if isinstance(x, (list, tuple)) and len(x):
        return str(x[0]).strip()
    return str(x).strip() if pd.notna(x) else ""

def assign_pred_windows_per_row(df: pd.DataFrame, th: Thresholds) -> pd.Series:
    """同一銘柄でしきい値を連続して満たす区間の開始〜終了(ET)を 'HH:MM–HH:MM' で返す。満たさない行は空欄。"""
    if df.empty or "_ts_et" not in df.columns: 
        return pd.Series([""]*len(df), index=df.index)

    if "symbols" in df.columns:
        key = df["symbols"].apply(_first_symbol_key)
    elif "symbol" in df.columns:
        key = df["symbol"].astype(str)
    elif "sector" in df.columns:
        key = df["sector"].astype(str)
    else:
        key = pd.Series([""]*len(df), index=df.index)

    need_cols = ("pred_vol","fake_rate","confidence")
    if not all(c in df.columns for c in need_cols):
        return pd.Series([""]*len(df), index=df.index)

    cond_all = (df["pred_vol"] >= th["pred_vol"]["yellow"]) & \
               (df["fake_rate"] <  th["fake_rate"]["orange"]) & \
               (df["confidence"] >= th["confidence"]["attention"])

    win = pd.Series([""]*len(df), index=df.index)
    for k, g in df.groupby(key):
        g = g.sort_values("_ts_utc")
        cond = cond_all.loc[g.index]
        if cond.sum() == 0:
            continue
        block_id = (cond != cond.shift()).cumsum()
        for bid, gg in g.groupby(block_id):
            if not cond.loc[gg.index].all():
                continue
            st_et = gg["_ts_et"].iloc[0]
            en_et = gg["_ts_et"].iloc[-1]
            st_s  = st_et.strftime("%H:%M") if pd.notna(st_et) else ""
            en_s  = en_et.strftime("%H:%M") if pd.notna(en_et) else ""
            win.loc[gg.index] = (st_s + "–" + en_s) if st_s and en_s else ""
    return win

# ====== 表生成（記号＋数値を同一セルに統合） ======
def build_table(df: pd.DataFrame, th: Thresholds, show_symbols: bool, timeband_label: str) -> Tuple[pd.DataFrame, PDStyler]:
    if df.empty:
        empty = pd.DataFrame()
        return empty, empty.style

    # ウォッチ行フラグを先に退避（列落ち対策）
    watch_mask = df["_is_watch"].copy() if "_is_watch" in df.columns else None

    out = df.copy()
    for c in ["_date_et","_time_et","time_band","sector","size","pred_vol","fake_rate","confidence","comment"]:
        if c not in out.columns:
            out[c] = "" if c in ("time_band","sector","size","comment") else pd.NA

    # 予想時間列
    pred_window = assign_pred_windows_per_row(out, th)
    out["pred_window_et"] = pred_window

    # 自動コメント → 表示は AIコメントのみ
    out["auto_comment"] = out.apply(lambda r: auto_comment(r, th), axis=1)

    # 日本語化
    out = out.rename(columns={
        "_date_et":"日付(ET)", "_time_et":"時刻(ET)", "time_band":"時間帯",
        "sector":"セクター","size":"サイズ",
        "symbols":"銘柄","auto_comment":"AIコメント",
        "pred_window_et":"予想時間(ET)"
    })

    # 記号＋数値（同セル）
    def sym_pred(v):
        if pd.isna(v): return "○ " + _fmt_both(v)
        if v >= th["pred_vol"]["red"]:    return "● " + _fmt_both(v)
        if v >= th["pred_vol"]["yellow"]: return "◉ " + _fmt_both(v)
        return "○ " + _fmt_both(v)

    def sym_fake(v):
        if pd.isna(v): return "□ " + _fmt_both(v)
        if v >= th["fake_rate"]["red"]:    return "■ " + _fmt_both(v)
        if v >= th["fake_rate"]["orange"]: return "▣ " + _fmt_both(v)
        return "□ " + _fmt_both(v)

    def sym_conf(v):
        if pd.isna(v): return "□ " + _fmt_both(v)
        if v >= th["confidence"]["high"]:      return "■ " + _fmt_both(v)
        if v >= th["confidence"]["attention"]: return "▣ " + _fmt_both(v)
        return "□ " + _fmt_both(v)

    raw_pred = out["pred_vol"].copy()
    raw_fake = out["fake_rate"].copy()
    raw_conf = out["confidence"].copy()

    out["予測ボラ"] = raw_pred.apply(sym_pred)
    out["だまし率"] = raw_fake.apply(sym_fake)
    out["信頼度"]   = raw_conf.apply(sym_conf)

    if show_symbols and "銘柄" not in out.columns and "symbols" in df.columns:
        out["銘柄"] = df["symbols"]

    # 表示列
    order = ["日付(ET)","時刻(ET)","予想時間(ET)","時間帯","セクター","サイズ","予測ボラ","だまし率","信頼度"]
    if "銘柄" in out.columns and show_symbols: order.append("銘柄")
    order.append("AIコメント")
    for c in order:
        if c not in out.columns:
            out[c] = ""
    out = out[order]

    # スタイリング（文字色）
    sty = out.style

    def style_col_by_values(raw: pd.Series, kind: str):
        def f(col: pd.Series):
            styles = []
            for idx in col.index:
                v = raw.get(idx, pd.NA)
                if pd.isna(v):
                    styles.append("")
                    continue
                if kind == "pred":
                    if v >= th["pred_vol"]["red"]:        styles.append("color:#ff6b6b")
                    elif v >= th["pred_vol"]["yellow"]:   styles.append("color:#d49500")
                    else:                                  styles.append("color:#666")
                elif kind == "fake":
                    if v >= th["fake_rate"]["red"]:       styles.append("color:#ff6b6b")
                    elif v >= th["fake_rate"]["orange"]:  styles.append("color:#f4a261")
                    else:                                  styles.append("color:#2d6a4f")
                elif kind == "conf":
                    if v >= th["confidence"]["high"]:     styles.append("color:#2d6a4f")
                    elif v >= th["confidence"]["attention"]: styles.append("color:#b38600")
                    else:                                  styles.append("color:#666")
                else:
                    styles.append("")
            return styles
        return f

    if "予測ボラ" in out.columns:
        sty = sty.apply(style_col_by_values(raw_pred, "pred"), subset=["予測ボラ"])
    if "だまし率" in out.columns:
        sty = sty.apply(style_col_by_values(raw_fake, "fake"), subset=["だまし率"])
    if "信頼度" in out.columns:
        sty = sty.apply(style_col_by_values(raw_conf, "conf"), subset=["信頼度"])

    sty = sty.set_table_styles([
        {"selector": "th.col_heading", "props": [("text-align","center")]},
        {"selector": "td", "props": [("vertical-align","middle")]}
    ])
    sty = sty.set_properties(subset=["予測ボラ","だまし率","信頼度","予想時間(ET)"], **{"text-align":"center"})

    # ウォッチ行の背景色（淡い黄色）
    if watch_mask is not None:
        watch_mask = watch_mask.reindex(out.index).fillna(False)
        def row_hl(row):
            on = bool(watch_mask.loc[row.name])
            return ["background-color:#fffbe6" if on else "" for _ in row]
        sty = sty.apply(row_hl, axis=1)

    return out, sty

def build_compare_table(snap_ja: pd.DataFrame, live_ja: pd.DataFrame) -> pd.DataFrame:
    if snap_ja.empty and live_ja.empty: return pd.DataFrame()
    common_keys = [c for c in ["日付(ET)","時刻(ET)","セクター","サイズ","銘柄"] if c in snap_ja.columns and c in live_ja.columns]
    if not common_keys:
        base = snap_ja.copy() if not snap_ja.empty else live_ja.copy()
        if (not live_ja.empty) and ("予測ボラ" in live_ja.columns):
            base["予測ボラ(ライブ)"] = live_ja["予測ボラ"].values[:len(base)]
        return base
    s_grp = snap_ja.groupby(common_keys, as_index=False).first()
    l_grp = live_ja.groupby(common_keys, as_index=False).first()
    merged = pd.merge(s_grp, l_grp[common_keys+["予測ボラ"]], on=common_keys, how="outer", suffixes=("","_live"))
    if "予測ボラ_live" in merged.columns:
        merged = merged.rename(columns={"予測ボラ_live":"予測ボラ(ライブ)"})
    base_order = ["日付(ET)","時刻(ET)","予想時間(ET)","時間帯","セクター","サイズ","予測ボラ","予測ボラ(ライブ)","だまし率","信頼度","銘柄","AIコメント"]
    cols = [c for c in base_order if c in merged.columns] + [c for c in merged.columns if c not in base_order]
    return merged[cols]

# ===== 差分用ユーティリティ =====
def _first_symbol_from_str(s: str) -> str:
    if not isinstance(s, str) or not s.strip(): return ""
    return s.split(",")[0].strip()

def _row_key_from_raw(row: pd.Series) -> str:
    sym = ""
    if "symbols" in row and isinstance(row["symbols"], str):
        sym = _first_symbol_from_str(row["symbols"])
    elif "symbol" in row and isinstance(row["symbol"], str):
        sym = row["symbol"]
    elif "sector" in row and isinstance(row["sector"], str):
        sym = row["sector"]
    t = ""
    if "_time_et" in row and pd.notna(row["_time_et"]):
        t = str(row["_time_et"])
    return f"{sym}|{t}"

def _make_prev_map(df_prev: pd.DataFrame) -> Dict[str, Tuple[float,float,float]]:
    if df_prev is None or df_prev.empty: return {}
    m = {}
    for i, r in df_prev.iterrows():
        k = _row_key_from_raw(r)
        if not k: continue
        pv = float(r.get("pred_vol", float("nan")))
        fr = float(r.get("fake_rate", float("nan")))
        cf = float(r.get("confidence", float("nan")))
        m[k] = (pv, fr, cf)
    return m

def make_delta_map(df_cur: pd.DataFrame, df_prev: pd.DataFrame) -> Tuple[Dict[int, Tuple[float,float,float]], Dict[str,int]]:
    if df_cur is None or df_cur.empty:
        return {}, {"new":0, "gone": len(df_prev) if isinstance(df_prev, pd.DataFrame) else 0, "changed":0}
    prev_map = _make_prev_map(df_prev if isinstance(df_prev, pd.DataFrame) else pd.DataFrame())
    cur_map_keys = set()
    delta_map: Dict[int, Tuple[float,float,float]] = {}
    changed = 0
    for idx, r in df_cur.iterrows():
        k = _row_key_from_raw(r)
        cur_map_keys.add(k)
        if k in prev_map:
            ppv, pfr, pcf = prev_map[k]
            cpv = float(r.get("pred_vol", float("nan")))
            cfr = float(r.get("fake_rate", float("nan")))
            ccf = float(r.get("confidence", float("nan")))
            d = (cpv-ppv, cfr-pfr, ccf-pcf)
            if any(abs(x) >= 1e-4 for x in d):
                changed += 1
            delta_map[idx] = d
        else:
            delta_map[idx] = (float("nan"), float("nan"), float("nan"))  # 新規
    new_ct  = sum(1 for k in cur_map_keys if k and k not in prev_map)
    gone_ct = sum(1 for k in prev_map.keys() if k and k not in cur_map_keys)
    return delta_map, {"new":new_ct, "gone":gone_ct, "changed":changed}

# --- Webhook: 強シグナル通知ヘルパー ----------------------------------------
def _fmt_num(v, pct: bool = False, nd_int: int = 3) -> str:
    try:
        if pd.isna(v):
            return "-"
        return (f"{float(v):.{nd_int}f}" if not pct else f"{float(v)*100:.1f}%")
    except Exception:
        return str(v)

def _row_by_key(df: pd.DataFrame, key: str) -> Optional[pd.Series]:
    """_row_key_from_raw(row) == key の先頭行を返す。無ければ None。"""
    try:
        m = df.apply(_row_key_from_raw, axis=1) == key
        if m.any():
            return df.loc[m].iloc[0]
    except Exception:
        pass
    return None

def send_signal_webhook(stream: str, key: str, df: Optional[pd.DataFrame] = None) -> None:
    """
    stream: 'Snap' / 'Live' など（通知本文に表示）
    key   : _row_key_from_raw と同じ形式 'SYMBOL|HH:MM'
    df    : 該当行の数値を本文に入れたい場合に渡す（無くても送信可）
    """
    # === ここから置き換え（先頭のガード強化） ===
    # UIを隠しているときは送らない（保険）
    if not SHOW_WEBHOOK_UI:
        return
    # 通知OFFなら送らない
    if not st.session_state.get("notify_enable", False):
        return
    # URL未設定なら送らない
    url = (st.session_state.get("notify_webhook_url") or "").strip()
    if not url:
        return
    # === ここまで置き換え ===

    # 本文の材料
    symbol = key.split("|")[0] if "|" in key else key
    t_et   = key.split("|")[1] if "|" in key and len(key.split("|")) > 1 else ""

    row = _row_by_key(df, key) if isinstance(df, pd.DataFrame) else None
    pv = row.get("pred_vol")    if isinstance(row, pd.Series) else None
    fr = row.get("fake_rate")   if isinstance(row, pd.Series) else None
    cf = row.get("confidence")  if isinstance(row, pd.Series) else None
    sector = row.get("sector")  if isinstance(row, pd.Series) else None
    size   = row.get("size")    if isinstance(row, pd.Series) else None

    title = (st.session_state.get("notify_title") or "VolAI 強シグナル").strip()
    text = (
        f"[{stream}] {symbol} {t_et}\n"
        f"予測ボラ: {_fmt_num(pv)} / だまし率: {_fmt_num(fr, pct=True, nd_int=2)} / 信頼度: {_fmt_num(cf, pct=True, nd_int=2)}\n"
        f"セクター: {sector or '-'} / サイズ: {size or '-'}"
    )

    # Slack/Discord どちらでも読める簡易ペイロード
    payload = {
        "text":    f"*{title}*\n{text}",     # Slack互換
        "content": f"**{title}**\n{text}",   # Discord互換
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        r.raise_for_status()
    except Exception as e:
        # 送信失敗はUIを止めない（情報として表示）
        st.info(f"Webhook送信失敗（無視可）: {e}")
# ---------------------------------------------------------------------------

def apply_delta_highlight(sty: PDStyler, df_cur: pd.DataFrame, delta_map: Dict[int, Tuple[float,float,float]]):
    def bg_for(col_name: str, pos_color: str, neg_color: str):
        def f(col: pd.Series):
            styles = []
            for idx in col.index:
                d = delta_map.get(idx)
                if not d:
                    styles.append("")
                    continue
                if col_name == "予測ボラ":
                    dv = d[0]
                elif col_name == "だまし率":
                    dv = d[1]
                elif col_name == "信頼度":
                    dv = d[2]
                else:
                    styles.append("")
                    continue
                if pd.isna(dv):
                    styles.append("background-color:#eef7ff")  # 新規（薄い青）
                elif abs(dv) < 1e-4:
                    styles.append("")
                else:
                    styles.append(f"background-color:{pos_color}" if dv > 0 else f"background-color:{neg_color}")
            return styles
        return f
    if "予測ボラ" in sty.data.columns:
        sty = sty.apply(bg_for("予測ボラ", "#fff4e6", "#e8f5e9"), subset=["予測ボラ"])
    if "だまし率" in sty.data.columns:
        sty = sty.apply(bg_for("だまし率", "#fdecea", "#e8f5e9"), subset=["だまし率"])
    if "信頼度" in sty.data.columns:
        sty = sty.apply(bg_for("信頼度", "#e8f5e9", "#fdecea"), subset=["信頼度"])
    return sty

# ===== 強シグナル検知 =====
def strong_signal_keys(df: pd.DataFrame, th: Thresholds) -> set:
    if df is None or df.empty: return set()
    m = (df["pred_vol"] >= th["pred_vol"]["red"]) & \
        (df["confidence"] >= th["confidence"]["high"]) & \
        (df["fake_rate"] <  th["fake_rate"]["orange"])
    keys = set()
    for _, r in df[m].iterrows():
        k = _row_key_from_raw(r)
        if k: keys.add(k)
    return keys

# =========================
# 実行（APIはここだけ）
# =========================
def run_pipeline():
    try:
        th_now = to_thresholds_from_session()

        # 前回のフィルタ済みを退避（差分用）
        prev_snap = st.session_state.get("snap_filtered", pd.DataFrame())
        prev_live = st.session_state.get("live_filtered", pd.DataFrame())

        with st.spinner("取得中…"):
            df_snap, err1 = fetch_latest(n=n, mode_live=False)
            df_live, err2 = fetch_latest(n=n, mode_live=True)

        # 退避した“前回”をセッションへ保存
        st.session_state["snap_prev"] = prev_snap
        st.session_state["live_prev"] = prev_live

        # 今回の生データを保存
        st.session_state["snap_raw"] = df_snap
        st.session_state["live_raw"] = df_live

        if err1: st.error(f"スナップショット読み込み失敗: {err1}")
        if err2: st.info("ライブ取得は未対応（/api/predict/latest?mode=live が無いか失敗）。スナップショットのみ表示します。")

        st.session_state["last_counts"] = (len(df_snap), len(df_live))

        if df_snap.empty and df_live.empty:
            st.warning("データが0件でした。取得件数・フィルタ・API Base を確認してください。")
            st.session_state["run_has_result"] = True
            st.session_state["snap_filtered"] = pd.DataFrame()
            st.session_state["live_filtered"] = pd.DataFrame()
            st.session_state["cmp_df"] = pd.DataFrame()
            st.session_state["summary_defaults"] = (None, None)
            st.session_state["steps_snap"] = []
            st.session_state["steps_live"] = []
            st.session_state["debug_window"] = {}
            st.session_state["debug_preview"] = pd.DataFrame()
            st.session_state["debug_timefix"] = {}
            return

        resolved_date = resolve_target_date_for_filter(st.session_state["target_date"], df_snap if not df_snap.empty else df_live)
        if resolved_date is None:
            resolved_date = datetime.now(ZoneInfo("America/Toronto")).date()

        price_min_in = float(st.session_state.get("price_min_in", 0.0))
        price_max_in = float(st.session_state.get("price_max_in", 0.0))
        mkt_min_in   = float(st.session_state.get("mkt_min_in", 0.0))
        mkt_max_in   = float(st.session_state.get("mkt_max_in", 0.0))

        # 時刻窓のデバッグ情報
        tz = ZoneInfo(st.session_state["tz_name"])
        presets = {
            "プレ（04:30–09:30 ET）": (time(4,30),  time(9,30)),
            "レギュラーam（09:30–12:00 ET）": (time(9,30), time(12,0)),
            "レギュラーpm（12:00–16:00 ET）": (time(12,0), time(16,0)),
            "アフター（16:00–20:00 ET）": (time(16,0), time(20,0)),
            "拡張（04:30–20:00 ET）": (time(4,30),  time(20,0)),
            "手入力": (st.session_state.get("manual_start"), st.session_state.get("manual_end")),
        }
        s_et, e_et = presets.get(st.session_state["band"], (None, None))
        if s_et and e_et:
            start_et = datetime.combine(resolved_date, s_et, tzinfo=tz)
            end_et   = datetime.combine(resolved_date, e_et, tzinfo=tz)
            st.session_state["debug_window"] = {
                "resolved_date_et": str(resolved_date),
                "tz_name": st.session_state["tz_name"],
                "band": st.session_state["band"],
                "start_et": start_et.isoformat(),
                "end_et": end_et.isoformat(),
                "start_utc": start_et.astimezone(ZoneInfo("UTC")).isoformat(),
                "end_utc": end_et.astimezone(ZoneInfo("UTC")).isoformat(),
            }
        else:
            st.session_state["debug_window"] = {}

        # フィルタチェーン
        def apply_all(df_in: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], List[int]]:
            steps = [len(df_in)]
            out = df_in.copy()
            out = filter_by_date_time_et(out, target_date_et=resolved_date, band_label=st.session_state["band"],
                                         manual_start=st.session_state.get("manual_start"), manual_end=st.session_state.get("manual_end"),
                                         tz_name=st.session_state["tz_name"])
            steps.append(len(out))
            out = filter_by_sector_size(out, sectors=st.session_state.get("sectors", []), sizes=st.session_state.get("ui_sizes", []))
            steps.append(len(out))
            out, notes = filter_by_ranges(
                out,
                (None if price_min_in==0.0 else float(price_min_in)),
                (None if price_max_in==0.0 else float(price_max_in)),
                (None if mkt_min_in  ==0.0 else float(mkt_min_in)),
                (None if mkt_max_in  ==0.0 else float(mkt_max_in)),
            )
            steps.append(len(out))
            return out, notes, steps

        # 既存
        df_snap_f, notes1, steps_snap = apply_all(df_snap)
        df_live_f, notes2, steps_live = (
            apply_all(df_live) if not df_live.empty else (pd.DataFrame(), [], [])
        )

        # Step: ウォッチリスト適用
        df_snap_f = apply_watchlist(df_snap_f)
        if not df_live_f.empty:
            df_live_f = apply_watchlist(df_live_f)

        # セッションへ格納
        st.session_state["snap_filtered"] = df_snap_f
        st.session_state["live_filtered"] = df_live_f
        st.session_state["steps_snap"] = steps_snap
        st.session_state["steps_live"] = steps_live

        # 取得直後プレビュー
        def preview(df_src: pd.DataFrame) -> pd.DataFrame:
            if df_src.empty: return pd.DataFrame()
            cols = [c for c in ["_date_et","_time_et","time_band","sector","size","pred_vol","fake_rate","confidence"] if c in df_src.columns]
            out = df_src[cols].head(50).copy()
            out = out.rename(columns={"_date_et":"ET日","_time_et":"ET時刻","time_band":"時間帯"})
            return out
        st.session_state["debug_preview"] = preview(df_snap if not df_snap.empty else df_live)

        # 比較テーブル
        th_now = to_thresholds_from_session()
        tableL = pd.DataFrame(); tableR = pd.DataFrame()
        if not df_snap_f.empty:
            tableL, _ = build_table(df_snap_f, th_now, st.session_state.get("show_symbols", True), st.session_state["band"])
        if not df_live_f.empty:
            tableR, _ = build_table(df_live_f, th_now, st.session_state.get("show_symbols", True), st.session_state["band"])
        st.session_state["cmp_df"] = build_compare_table(tableL if isinstance(tableL, pd.DataFrame) else pd.DataFrame(),
                                                         tableR if isinstance(tableR, pd.DataFrame) else pd.DataFrame())

        # サマリ既定期間
        tz_et = ZoneInfo("America/Toronto")
        base_df = df_snap_f if not df_snap_f.empty else df_live_f
        if not base_df.empty:
            latest_dt = base_df["_ts_utc"].dt.tz_convert(tz_et).max()
            base_date = latest_dt.date() if not pd.isna(latest_dt) else date.today()
        else:
            base_date = date.today()
        st.session_state["summary_defaults"] = (base_date, base_date)

        st.session_state["notes_joined"] = " / ".join([*notes1, *notes2])
        st.session_state["run_has_result"] = True

    except Exception as e:
        st.error(f"実行中にエラー：{e}")
        st.code(traceback.format_exc())
        st.session_state["run_has_result"] = True

# 自動更新ONでも毎リランで取得するように
if run_clicked or st.session_state.get("auto_refresh_on"):
    run_pipeline()

# =========================
# 表示（直近の実行結果）
# =========================
def render_styler(sty: PDStyler, height: int = 420):
    try:
        html = sty.to_html()
        st.markdown(f'<div style="overflow:auto; border:1px solid #eee; max-height:{height}px">{html}</div>', unsafe_allow_html=True)
    except Exception:
        st.write(sty)

if st.session_state.get("run_has_result", False):
    snapN, liveN = st.session_state["last_counts"]
    st.success(f"取得・整形完了：スナップショット {snapN} 件 / ライブ {liveN} 件")

    df_snap_f = st.session_state["snap_filtered"]
    df_live_f = st.session_state["live_filtered"]
    th_now = to_thresholds_from_session()

    with st.expander("比較テーブル（オプション）", expanded=False):
        cmp_df = st.session_state["cmp_df"]
        if cmp_df.empty:
            st.info("比較テーブルを作成できませんでした（キー不一致またはデータ不足）。")
        else:
            st.dataframe(cmp_df, use_container_width=True, height=420)

    with st.expander("フィルタ適用の内訳", expanded=False):
        steps_snap = st.session_state.get("steps_snap", [])
        steps_live = st.session_state.get("steps_live", [])
        if steps_snap:
            st.write(f"スナップショット: {steps_snap[0]} → 時間 {steps_snap[1]} → サイズ/セクター {steps_snap[2]} → レンジ {steps_snap[3]}")
        if steps_live:
            st.write(f"ライブ: {steps_live[0]} → 時間 {steps_live[1]} → サイズ/セクター {steps_live[2]} → レンジ {steps_live[3]}")

    with st.expander("デバッグ：時刻チェック（ET/UTC）", expanded=False):
        dbg = st.session_state.get("debug_window", {})
        if dbg:
            st.write(f"対象日(ET): {dbg['resolved_date_et']} / 帯: {dbg['band']} / TZ: {dbg['tz_name']}")
            st.write(f"開始ET: {dbg['start_et']}  →  開始UTC: {dbg['start_utc']}")
            st.write(f"終了ET: {dbg['end_et']}    →  終了UTC: {dbg['end_utc']}")
        tf = st.session_state.get("debug_timefix", {})
        if tf:
            st.write(f"日付自動合わせ: {tf.get('date_auto_aligned')} / 合わせ先: {tf.get('aligned_date_et')}")
            st.write(f"補正適用: {tf.get('auto_fix_applied')} / 窓ヒット(前→後): {tf.get('hit_before')} → {tf.get('hit_after')} / 補正時差(h): {tf.get('offset_hours')}")
            st.write(f"UTC範囲 min/max: {tf.get('raw_min_utc')} / {tf.get('raw_max_utc')}")
            st.write(f"ET 範囲 min/max: {tf.get('raw_min_et')} / {tf.get('raw_max_et')}")
        prev = st.session_state.get("debug_preview", pd.DataFrame())
        if not prev.empty:
            st.markdown("**取得データのET時刻プレビュー（先頭50件）**")
            st.dataframe(prev, use_container_width=True, height=300)
        else:
            st.write("プレビューなし（データ0件）")

    st.markdown("---")
    st.subheader("スナップショット（日本語＋色つき）")
    if df_snap_f.empty:
        st.info("スナップショットは0件。")
    else:
        delta_map_snap, badges_snap = make_delta_map(df_snap_f, st.session_state.get("snap_prev", pd.DataFrame()))
        new_keys = strong_signal_keys(df_snap_f, th_now)
        seen = st.session_state.get("alert_seen_snap", set())
        to_alert = new_keys
        if st.session_state.get("alert_only_watchlist", False):
            wl = parse_watchlist(st.session_state.get("watchlist_str"))
            to_alert = {k for k in new_keys if (k.split("|")[0].upper() in wl)}
        for k in (to_alert - seen):
            st.toast(f"📈 強シグナル（Snap）: {k}", icon="🔥")
            # ここが修正点: 未定義の row を渡していた行を削除し、df_snap_f を渡す
            send_signal_webhook("Snap", k, df_snap_f)
        st.session_state["alert_seen_snap"] |= new_keys

        st.caption(f"Δ 新規: {badges_snap['new']} / 消滅: {badges_snap['gone']} / 変化: {badges_snap['changed']}")

        _, styled_snap = build_table(df_snap_f, th_now, st.session_state.get("show_symbols", True), st.session_state["band"])
        if st.session_state.get("diff_on", True):
            styled_snap = apply_delta_highlight(styled_snap, df_snap_f, delta_map_snap)
        render_styler(styled_snap, height=420)

    st.subheader("ライブ（日本語＋色つき）")
    if df_live_f.empty:
        st.info("ライブ表示なし（API未実装 or 0件）。")
    else:
        delta_map_live, badges_live = make_delta_map(df_live_f, st.session_state.get("live_prev", pd.DataFrame()))
        new_keys = strong_signal_keys(df_live_f, th_now)
        seen = st.session_state.get("alert_seen_live", set())
        to_alert = new_keys
        if st.session_state.get("alert_only_watchlist", False):
            wl = parse_watchlist(st.session_state.get("watchlist_str"))
            to_alert = {k for k in new_keys if (k.split("|")[0].upper() in wl)}
        for k in (to_alert - seen):
            st.toast(f"📡 強シグナル（Live）: {k}", icon="⚡")
            send_signal_webhook("Live", k, df_live_f)
        st.session_state["alert_seen_live"] |= new_keys

        st.caption(f"Δ 新規: {badges_live['new']} / 消滅: {badges_live['gone']} / 変化: {badges_live['changed']}")
        _, styled_live = build_table(df_live_f, th_now, st.session_state.get("show_symbols", True), st.session_state["band"])
        if st.session_state.get("diff_on", True):
            styled_live = apply_delta_highlight(styled_live, df_live_f, delta_map_live)
        render_styler(styled_live, height=420)

    # 適用メモ（1箇所のみ・重複排除）
    notes_joined = st.session_state["notes_joined"]
    if notes_joined:
        st.caption("※適用メモ: " + notes_joined)

    # ▼ 設定のエクスポート/インポート（JSON）— 「エクスポート」見出しの直前
    with st.expander("設定のエクスポート/インポート（JSON）", expanded=False):
        c1, c2 = st.columns(2)

        with c1:
            cfg = collect_settings()
            payload = {
                "meta": {"app": "vol_ai_ui", "ver": 1, "ts": datetime.now().isoformat()},
                "settings": cfg,
            }
            st.download_button(
                "設定をJSONでダウンロード",
                data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
                key="dl_settings_json",
            )

        with c2:
            up = st.file_uploader("設定JSONを読み込む", type=["json"], accept_multiple_files=False, key="ul_settings_json")
            if up is not None:
                try:
                    data = json.load(up)
                    settings = data.get("settings", data)
                    if isinstance(settings, dict):
                        apply_settings(settings)
                        st.success("設定を反映しました（UIを再描画します）")
                        try:
                            st.experimental_rerun()
                        except Exception:
                            st.rerun()
                    else:
                        st.warning("JSON形式が不正です（'settings' が辞書ではありません）。")
                except Exception as e:
                    st.error(f"読込に失敗しました: {e}")

    # ===== エクスポート（スナップ/ライブの表の後〜 サマリ前） =====
    st.markdown("### エクスポート")

    def _to_csv_bytes(df: pd.DataFrame) -> bytes:
        return df.to_csv(index=False).encode("utf-8-sig")

    def _to_xlsx_bytes(df: pd.DataFrame) -> bytes:
        if df is None or df.empty:
            return b""
        buf = io.BytesIO()
        engine_order = ["openpyxl", "xlsxwriter"]
        last_err = None
        for eng in engine_order:
            try:
                with pd.ExcelWriter(buf, engine=eng) as writer:
                    df.to_excel(writer, index=False, sheet_name="data")
                buf.seek(0)
                return buf.getvalue()
            except Exception as e:
                last_err = e
                buf.seek(0); buf.truncate(0)
                continue
        raise last_err or RuntimeError("No Excel engine available")

    exp_c1, exp_c2, exp_c3, exp_c4 = st.columns(4)
    with exp_c1:
        st.download_button("スナップショットCSV", _to_csv_bytes(df_snap_f), "snapshot.csv",
                           mime="text/csv", disabled=df_snap_f.empty, key="dl_snap_csv")
    with exp_c2:
        st.download_button("ライブCSV", _to_csv_bytes(df_live_f), "live.csv",
                           mime="text/csv", disabled=df_live_f.empty, key="dl_live_csv")
    with exp_c3:
        both = pd.concat([
            df_snap_f.assign(_kind="snapshot"),
            df_live_f.assign(_kind="live")
        ], ignore_index=True) if (not df_snap_f.empty or not df_live_f.empty) else pd.DataFrame()
        st.download_button("両方CSV", _to_csv_bytes(both), "both.csv",
                           mime="text/csv", disabled=both.empty, key="dl_both_csv")
    with exp_c4:
        try:
            st.download_button("スナップショットExcel", _to_xlsx_bytes(df_snap_f), "snapshot.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               disabled=df_snap_f.empty, key="dl_snap_xlsx")
        except Exception as e:
            st.caption(f"Excel出力エンジン未導入のため無効です：{e}")

    # ===== サマリ & ヒートマップ =====
    st.markdown("---")
    st.subheader("サマリ（期間カスタム・時間帯×セクター・ヒートマップ）")

    tgt_kind = st.selectbox("対象", ["スナップショット","ライブ（ある場合）"], index=0)
    df_target = df_snap_f if tgt_kind == "スナップショット" else df_live_f

    tz_et = ZoneInfo("America/Toronto")
    base_start, base_end = st.session_state.get("summary_defaults", (date.today(), date.today()))
    period_mode = st.radio("粒度", ["日","週","月","カスタム"], horizontal=True, index=0)

    def week_range_containing(d: date) -> Tuple[date, date]:
        weekday = d.weekday()
        start = d - timedelta(days=weekday)
        end   = start + timedelta(days=4)
        return start, end

    base_date = base_start or date.today()
    if period_mode == "日":
        sum_start, sum_end = base_date, base_date
    elif period_mode == "週":
        sum_start, sum_end = week_range_containing(base_date)
    elif period_mode == "月":
        sum_start = date(base_date.year, base_date.month, 1)
        sum_end = (date(base_date.year+1,1,1) - timedelta(days=1)) if base_date.month==12 else (date(base_date.year, base_date.month+1, 1) - timedelta(days=1))
    else:
        cc2, cc3 = st.columns(2)
        with cc2:
            sum_start = st.date_input("サマリ開始日（ET）", value=base_start or base_date, key="sum_start_custom")
        with cc3:
            sum_end   = st.date_input("サマリ終了日（ET）", value=base_end or base_date, key="sum_end_custom")

    def summarize_extended(df: pd.DataFrame, start_date_et: date, end_date_et: date) -> pd.DataFrame:
        if df.empty or "_ts_utc" not in df.columns: return pd.DataFrame()
        tz = ZoneInfo("America/Toronto")
        start_dt = datetime.combine(start_date_et, time(0,0), tzinfo=tz).astimezone(ZoneInfo("UTC"))
        end_dt   = datetime.combine(end_date_et + timedelta(days=1), time(0,0), tzinfo=tz).astimezone(ZoneInfo("UTC"))
        d = df[(df["_ts_utc"] >= start_dt) & (df["_ts_utc"] < end_dt)].copy()
        if d.empty: return pd.DataFrame()
        d["時間帯"] = d["time_band"] if "time_band" in d.columns else ""
        if "sector" in d.columns: d["セクター"] = d["sector"]

        def agg_comments(series: pd.Series) -> str:
            vals = [x.strip() for x in series if isinstance(x,str) and x.strip()]
            uniq = []
            for x in vals:
                if x not in uniq:
                    uniq.append(x)
            joined = " / ".join(uniq[:3])
            return joined[:180]

        g = d.groupby(["時間帯","セクター"], dropna=False)
        out = g.agg(
            件数=("時間帯","count"),
            予測ボラ_avg=("pred_vol","mean"),
            だまし率_avg=("fake_rate","mean"),
            信頼度_avg=("confidence","mean"),
            コメント例=("comment", agg_comments) if "comment" in d.columns else ("時間帯","first"),
        ).reset_index()
        for c in ["予測ボラ_avg","だまし率_avg","信頼度_avg"]:
            out[c] = out[c].round(3)
        return out

    sm = summarize_extended(df_target, sum_start, sum_end)
    if sm.empty:
        st.info("サマリ対象なし（期間・フィルタをご確認ください）。")
    else:
        st.dataframe(sm, use_container_width=True, height=320)

        if importlib.util.find_spec("altair"):
            import altair as alt
            st.markdown("**ヒートマップ：平均予測ボラ（％表示）**")
            hm = sm.copy()
            hm["予測ボラ_pct"] = (hm["予測ボラ_avg"] * 100).round(1)
            hm["帯"] = hm["時間帯"].astype(str).str.replace("（.*?）","", regex=True)
            band_order = ["プレ","レギュラーam","レギュラーpm","アフター","拡張"]

            chart = alt.Chart(hm).mark_rect(stroke="white").encode(
                x=alt.X("帯:O", sort=band_order, title="時間帯"),
                y=alt.Y("セクター:O", sort=alt.SortField(field="件数", order="descending"), title="セクター"),
                color=alt.Color("予測ボラ_avg:Q", title="平均予測ボラ", scale=alt.Scale(scheme="reds")),
                tooltip=["セクター","帯","件数","予測ボラ_avg","だまし率_avg","信頼度_avg","コメント例"]
            ).properties(width=520, height=360)

            labels = alt.Chart(hm).mark_text(baseline='middle', fontSize=12, fontWeight='bold', color="black").encode(
                x=alt.X("帯:O", sort=band_order),
                y=alt.Y("セクター:O", sort=alt.SortField(field="件数", order="descending")),
                text=alt.Text("予測ボラ_pct:Q", format=",.1f")
            )
            st.altair_chart(chart + labels, use_container_width=True)
        else:
            st.markdown("**ヒートマップ（簡易フォールバック）**")
            hm = sm.pivot(index="セクター", columns="時間帯", values="予測ボラ_avg").fillna(0.0)
            sty = hm.style.background_gradient(cmap="Reds").format("{:.3f}")
            try:
                html = sty.to_html()
                st.markdown(f'<div style="overflow:auto; border:1px solid #eee; max-height:380px">{html}</div>', unsafe_allow_html=True)
            except Exception:
                st.write(sty)

    # =========================
    # 現在のユーザー
    # =========================
    st.markdown("---")
    st.subheader("現在のユーザー")
    if st.session_state.get("me"):
        st.json(st.session_state["me"])
    else:
        st.write("未ログイン")