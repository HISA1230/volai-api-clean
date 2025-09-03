# -*- coding: utf-8 -*-
"""
Streamlit UI — 見栄え仕上げ v1（互換ブリッジ & 柔軟ペイロード対応）
- 固定列: 日付(ローカル) / 時間帯 / セクター / サイズ / 予測ボラ / だまし率 / 信頼度 / コメント / 推奨
- 絵文字バッジ & フィルタ付き
- /api/predict/latest が 404 の場合は /api/strategy/latest にフォールバック
- {"data":[...]} 等の dict 返却にも対応（data/rows/items/result/records または dict-of-dicts）
"""

from __future__ import annotations
import os
import re
import math
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd
import requests
import streamlit as st

# --------------------------------------------
# ページ設定
# --------------------------------------------
st.set_page_config(page_title="Volatility AI — Predict View", page_icon="📈", layout="wide")

# --- session_state 初期化と遅延リセット処理（ウィジェット生成より前に！） ---
if "min_conf" not in st.session_state:
    st.session_state["min_conf"] = 0.0
if "max_fake" not in st.session_state:
    st.session_state["max_fake"] = 1.0
# 中央/サイドバーのリセットボタンからフラグが立っていたら、ここで実リセット
if st.session_state.get("_defer_reset", False):
    st.session_state["min_conf"] = 0.0
    st.session_state["max_fake"] = 1.0
    st.session_state["_defer_reset"] = False

# --------------------------------------------
# ユーティリティ
# --------------------------------------------
def _parse_num(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"[-+]?[0-9]*\.?[0-9]+", str(x))
    return float(m.group(0)) if m else None


def _compat_bridge(df: pd.DataFrame) -> pd.DataFrame:
    """
    入力 DataFrame を標準スキーマへ正規化:
      ts_utc, sector, symbols, time_band, pred_vol, confidence, fake_rate, size, market_cap, price
    - JPカラム: 時刻/セクター/銘柄/窓[h]/平均スコア(色)/ポジ比率/時価総額/終値 など
    - ENカラム: ts/window_hours/avg_score/pos_ratio/market_cap/... など
    """
    if df is None or df.empty:
        return df
    df = df.copy()

    # --- JP→標準 ---
    ren = {}
    if "時刻" in df.columns:     ren["時刻"]   = "ts_utc"
    if "セクター" in df.columns: ren["セクター"] = "sector"
    if "銘柄" in df.columns:     ren["銘柄"]   = "symbols"
    if "終値" in df.columns:      ren.setdefault("終値", "price")
    if "株価" in df.columns:      ren.setdefault("株価", "price")
    if ren:
        df.rename(columns=ren, inplace=True)

    # --- EN→標準 ---
    if "ts" in df.columns and "ts_utc" not in df.columns:
        df.rename(columns={"ts": "ts_utc"}, inplace=True)

    # time_band ← 窓[h] or window_hours → "24h" 等
    if "time_band" not in df.columns:
        if "窓[h]" in df.columns:
            df["time_band"] = df["窓[h]"].apply(lambda v: f"{int(v)}h" if pd.notna(v) and str(v) != "" else "")
        elif "window_hours" in df.columns:
            def _fmt(v):
                try:
                    return f"{int(float(v))}h" if pd.notna(v) else ""
                except Exception:
                    return ""
            df["time_band"] = df["window_hours"].map(_fmt)
        else:
            df["time_band"] = ""

    # pred_vol ← 平均スコア(色) or avg_score
    if "pred_vol" not in df.columns:
        if "平均スコア(色)" in df.columns:
            df["pred_vol"] = df["平均スコア(色)"].map(_parse_num)
        elif "avg_score" in df.columns:
            df["pred_vol"] = pd.to_numeric(df["avg_score"], errors="coerce")

    # confidence ← ポジ比率 or pos_ratio
    if "confidence" not in df.columns:
        if "ポジ比率" in df.columns:
            df["confidence"] = df["ポジ比率"].map(_parse_num)
        elif "pos_ratio" in df.columns:
            df["confidence"] = pd.to_numeric(df["pos_ratio"], errors="coerce")

    # price（ペニー判定の補助・任意）
    if "price" not in df.columns:
        for c in ["last", "last_price", "close", "adj_close"]:
            if c in df.columns:
                df.rename(columns={c: "price"}, inplace=True)
                break
    if "price" in df.columns:
        df["price"] = pd.to_numeric(df["price"], errors="coerce")

    # size ラベル（既存の表記を標準化）
    if "size" not in df.columns:
        for c in ["Size", "cap_size", "size_class", "size_category", "サイズ"]:
            if c in df.columns:
                df.rename(columns={c: "size"}, inplace=True)
                break
    if "size" in df.columns:
        def _norm_size(s):
            if s is None or (isinstance(s, float) and pd.isna(s)):
                return ""
            t = str(s).strip().lower()
            t2 = re.sub(r"[^a-z]", "", t)
            if t2 in ("large","larges","lg","megacap","mega","xl"): return "Large"
            if t2 in ("mid","midcap","medium","md"):                return "Mid"
            if t2 in ("small","smallcap","sm"):                     return "Small"
            if t2 in ("micro","microcap","mc","nano","nanocap"):    return "Micro"
            if "penny" in t:                                       return "Penny"
            if t in ("大","大型"):   return "Large"
            if t in ("中","中型"):   return "Mid"
            if t in ("小","小型"):   return "Small"
            if t in ("極小","ﾏｲｸﾛ"): return "Micro"
            return ""
        df["size"] = df["size"].map(_norm_size)
    else:
        df["size"] = ""

    # market_cap（候補名が無ければ欠損のまま）
    if "market_cap" not in df.columns:
        for c in ("market_cap","marketcap","mktcap","market_capitalization","時価総額"):
            if c in df.columns:
                df.rename(columns={c: "market_cap"}, inplace=True)
                break
    if "market_cap" in df.columns:
        df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")

    # デフォルト列
    if "fake_rate" not in df.columns:
        df["fake_rate"] = None
    if "symbols" not in df.columns:
        df["symbols"] = ""

    # ---- 追加フォールバック：セレクタが空にならないよう最低限の値を埋める ----
    # time_band が全て空なら window_hours → "Nh" で復元。なければデモ用 "24h"
    try:
        tb = df["time_band"].fillna("")
        if tb.eq("").all():
            if "window_hours" in df.columns:
                df["time_band"] = df["window_hours"].map(lambda v: f"{int(v)}h" if pd.notna(v) else "")
            # それでも空なら 24h を入れてフィルタを生かす
            if df["time_band"].fillna("").eq("").all():
                df["time_band"] = "24h"
    except Exception:
        pass

    # size が全て空で volume があるなら、出来高で簡易分類（デモ用）
    try:
        sz = df["size"].fillna("")
        if sz.eq("").all() and "volume" in df.columns:
            def _size_by_volume(v):
                try:
                    v = float(v)
                except Exception:
                    return ""
                if v >= 35: return "Large"
                elif v >= 18: return "Mid"
                elif v >= 8:  return "Small"
                elif v > 0:   return "Micro"
                else:         return ""
            df["size"] = df["volume"].map(_size_by_volume)
    except Exception:
        pass

    return df


def _extract_listlike(payload: Any) -> list:
    """
    API返却からレコード list を抽出:
      - list[dict]
      - {"data"| "rows"| "items"| "result"| "records": [...]}
      - dict-of-dicts（values を採用）
      - {"columns":[...], "data":[...]} は data を採用
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "rows", "items", "result", "records"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
        if payload and all(isinstance(v, dict) for v in payload.values()):
            return list(payload.values())
        v = payload.get("data")
        if isinstance(v, list):
            return v
    return []


@st.cache_data(show_spinner=False, ttl=15)
def fetch_predict_latest(base: str, n: int = 200) -> pd.DataFrame:
    """
    /api/predict/latest を優先、404 なら /api/strategy/latest にフォールバック。
    柔軟な payload 形状にも対応。
    """
    base = base.rstrip("/")
    predict_url = f"{base}/api/predict/latest"
    strat_url   = f"{base}/api/strategy/latest"

    used = None
    payload = None

    try:
        r = requests.get(predict_url, params={"n": n}, timeout=(5, 20))
        if r.status_code == 404:
            raise requests.HTTPError("404 on /api/predict/latest", response=r)
        r.raise_for_status()
        payload = r.json()
        used = "/api/predict/latest"
    except Exception as e1:
        try:
            r = requests.get(strat_url, params={"n": n}, timeout=(5, 20))
            if r.status_code == 400:
                r = requests.get(strat_url, timeout=(5, 20))
            r.raise_for_status()
            payload = r.json()
            used = "/api/strategy/latest"
        except Exception as e2:
            raise RuntimeError(
                f"API 呼び出しに失敗: {predict_url} / {strat_url}\n- {e1}\n- {e2}"
            )

    st.session_state["endpoint_used"] = used
    data = _extract_listlike(payload) or []
    st.session_state["payload_shape"] = f"{type(payload).__name__} -> list[{len(data)}]"

    df = pd.DataFrame(data)
    df = _compat_bridge(df)

    # 欠損カラム補完
    for col in [
        "ts_utc", "time_band", "sector", "size",
        "pred_vol", "fake_rate", "confidence",
        "comment", "rec_action", "symbols",
    ]:
        if col not in df.columns:
            df[col] = None

    # ts_utc（UTC）→ ローカル文字列
    def to_local(ts: Any) -> str:
        if ts in (None, "", float("nan")):
            return ""
        try:
            s = pd.to_datetime(ts, utc=True, errors="coerce")
            if pd.isna(s):
                return str(ts)
            local_tz = datetime.now().astimezone().tzinfo
            s_local = s.tz_convert(local_tz)
            return s_local.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)

    if "ts_utc" in df.columns:
        df["date_local"] = df["ts_utc"].map(to_local)
    else:
        df["date_local"] = ""

    # symbols 正規化
    def norm_symbols(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, list):
            return ", ".join(map(str, v))
        return str(v)
    df["symbols"] = df["symbols"].map(norm_symbols)

    # 数値化
    def to_float(x: Any) -> Optional[float]:
        try:
            if x is None:
                return None
            if isinstance(x, (int, float)):
                return float(x)
            if isinstance(x, str) and x.strip() == "":
                return None
            return float(x)
        except Exception:
            return None
    for col in ["pred_vol", "fake_rate", "confidence"]:
        df[col] = df[col].map(to_float)

    return df


def grade_with_emoji(value: Optional[float], hi: float, mid: float, *, positive_good: bool) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "▫️ N/A"
    disp = f"{value*100:.1f}%" if globals().get("USE_PERCENT_BADGE", False) else f"{value:.2f}"
    if positive_good:
        if value >= hi:   return f"🟢 {disp}"
        elif value >= mid:return f"🟠 {disp}"
        else:             return f"⚪ {disp}"
    else:
        if value >= hi:   return f"🔴 {disp}"
        elif value >= mid:return f"🟠 {disp}"
        else:             return f"🟢 {disp}"


def pick_rec_emoji(action: Any, fake_rate: Optional[float], conf: Optional[float]) -> str:
    s = str(action or "").lower()
    if any(k in s for k in ["buy", "long", "enter", "go long"]):
        return "🟢📈"
    if any(k in s for k in ["short", "sell", "take profit"]):
        return "🔻"
    if any(k in s for k in ["avoid", "skip", "no trade"]):
        return "⛔"
    if any(k in s for k in ["watch", "hold", "wait"]):
        return "👀"
    if conf and conf >= 0.7 and (fake_rate is None or fake_rate < 0.3):
        return "✅"
    if fake_rate and fake_rate >= 0.6:
        return "⚠️"
    return "🔎"


# --------------------------------------------
# サイドバー（設定）
# --------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定")

    default_base = os.getenv("VOLAI_API_BASE", "http://127.0.0.1:8021")
    base_url = st.text_input("API Base URL", value=default_base, help="例: https://volai-api-02.onrender.com")

    n = st.slider("取得件数 (n)", 20, 1000, 200, step=20)
    lookback_h = st.slider("直近だけ表示 (hours)", 1, 168, 48)

    st.markdown("---")
    st.caption("しきい値（バックエンドと揃える）")
    col1, col2 = st.columns(2)
    with col1:
        vol_hi  = st.number_input("予測ボラ: High ≥", value=0.70, min_value=0.0, max_value=1.0, step=0.05)
        vol_mid = st.number_input("予測ボラ: Mid ≥",  value=0.40, min_value=0.0, max_value=1.0, step=0.05)
        fake_hi = st.number_input("だまし率: High ≥", value=0.60, min_value=0.0, max_value=1.0, step=0.05)
        fake_mid= st.number_input("だまし率: Mid ≥",  value=0.30, min_value=0.0, max_value=1.0, step=0.05)
    with col2:
        conf_hi = st.number_input("信頼度: High ≥",  value=0.70, min_value=0.0, max_value=1.0, step=0.05)
        conf_mid= st.number_input("信頼度: Mid ≥",   value=0.40, min_value=0.0, max_value=1.0, step=0.05)

        # プリセット（この時点ではまだスライダーは作らない）
        st.markdown("**表示プリセット**")
        preset = st.radio(
            "一発設定（あとから手動で微調整OK）",
            ["手動", "保守的（厳選）", "バランス（標準）", "探索（広め）"],
            index=0, horizontal=True,
            help="保守: CONF≥0.70 & FAKE≤0.30 ／ バランス: 0.60/0.40 ／ 探索: 0.50/0.60",
        )
        PRESETS = {
            "保守的（厳選）": {"min_conf": 0.70, "max_fake": 0.30},
            "バランス（標準）": {"min_conf": 0.60, "max_fake": 0.40},
            "探索（広め）":   {"min_conf": 0.50, "max_fake": 0.60},
        }
        if preset != "手動":
            tgt = PRESETS[preset]
            if (st.session_state["min_conf"], st.session_state["max_fake"]) != (tgt["min_conf"], tgt["max_fake"]):
                st.session_state["min_conf"] = tgt["min_conf"]
                st.session_state["max_fake"] = tgt["max_fake"]
                st.toast(f"プリセット「{preset}」適用：信頼度≥{tgt['min_conf']} / だまし率≤{tgt['max_fake']}")
                st.rerun()

    # サイドバーのリセット（細いカラムで“横一列表示”にして折り返し回避）
    sb_col, _ = st.columns([1.9, 8])
    with sb_col:
        if st.button("🔁 全表示にリセット", use_container_width=True, key="reset_sidebar"):
            st.session_state["_defer_reset"] = True
            st.rerun()

    # ここで初めてスライダーを作成（キーは session_state と一致）
    min_conf = st.slider("絞り込み: 最低信頼度", 0.0, 1.0, st.session_state["min_conf"], 0.05, key="min_conf")
    max_fake = st.slider("絞り込み: 最大だまし率", 0.0, 1.0, st.session_state["max_fake"], 0.05, key="max_fake")

    # サイズ分類（Penny含む）
    st.markdown("---")
    st.subheader("サイズ分類")
    size_mode = st.radio(
        "サイズの付け方",
        ["APIのまま", "時価総額で自動分類", "時価総額＋ペニー判定"],
        index=2,
        help="APIの size をそのまま使う／時価総額しきい値で Large/Mid/Small/Micro を付与／さらに Penny を判定して上書き"
    )
    if size_mode != "APIのまま":
        col_cap1, col_cap2, col_cap3 = st.columns(3)
        with col_cap1:
            large_min_b = st.number_input("Large 最小 ($B)", min_value=0.1, max_value=100.0, value=10.0, step=0.5)
        with col_cap2:
            mid_min_b   = st.number_input("Mid 最小 ($B)",   min_value=0.1, max_value=100.0, value=2.0,  step=0.5)
        with col_cap3:
            small_min_m = st.number_input("Small 最小 ($M)",  min_value=10.0, max_value=5000.0, value=300.0, step=10.0)

        col_cap4, col_cap5 = st.columns(2)
        with col_cap4:
            mid_max_b = st.number_input("Mid 最大 ($B)", min_value=0.1, max_value=100.0, value=10.0, step=0.5)
        with col_cap5:
            small_max_m = st.number_input("Small 最大 ($M)", min_value=10.0, max_value=5000.0, value=2000.0, step=10.0)

        msgs = []
        if mid_max_b > large_min_b:
            msgs.append(f"Mid最大({mid_max_b}B) を Large最小({large_min_b}B) に合わせました。")
            mid_max_b = large_min_b
        if mid_min_b >= mid_max_b:
            new_mid_max = min(large_min_b, max(mid_min_b + 0.1, mid_min_b * 1.01))
            msgs.append(f"Mid最小({mid_min_b}B) < Mid最大 を満たすよう Mid最大→{new_mid_max:.2f}B に補正。")
            mid_max_b = new_mid_max
        mid_min_m_eq = mid_min_b * 1000.0
        if small_max_m > mid_min_m_eq:
            msgs.append(f"Small最大({small_max_m}M) を Mid最小({mid_min_m_eq:.0f}M) に合わせました。")
            small_max_m = mid_min_m_eq
        if small_min_m >= small_max_m:
            new_small_max = small_min_m + 10.0
            msgs.append(f"Small最小({small_min_m}M) < Small最大 を満たすよう Small最大→{new_small_max:.0f}M に補正。")
            small_max_m = new_small_max

        st.caption(
            f"分類レンジ:  Large ≥ {large_min_b:.2f}B ｜ "
            f"Mid [{mid_min_b:.2f}B, {mid_max_b:.2f}B) ｜ "
            f"Small [{small_min_m:.0f}M, {small_max_m:.0f}M) ｜ "
            f"Micro < {small_min_m:.0f}M"
        )
        for m in msgs:
            st.info(m)

    penny_method = penny_price = penny_cap_m = penny_label = None
    if size_mode == "時価総額＋ペニー判定":
        st.markdown("**ペニー判定**")
        penny_method = st.radio(
            "判定方法",
            ["株価のみ (<$P)", "時価総額のみ (<$M)", "両方 (どちらか満たす)"],
            index=2, horizontal=True
        )
        col_p1, col_p2, col_p3 = st.columns([1,1,1.2])
        with col_p1:
            penny_price = st.number_input("株価しきい値 $P", min_value=0.1, max_value=20.0, value=5.0, step=0.1)
        with col_p2:
            penny_cap_m = st.number_input("時価総額しきい値 $M", min_value=1.0, max_value=5000.0, value=100.0, step=10.0)
        with col_p3:
            penny_label = st.text_input("ペニーのラベル", value="Penny", help="例：Penny / ペニー / 超小型 など")

    st.markdown("---")
    disp_mode = st.radio("数値表示", ["0–1", "%"], index=0, horizontal=True)
    USE_PERCENT_BADGE = (disp_mode == "%")

    st.markdown("---")
    refresh = st.button("🔄 再取得 / Refresh", use_container_width=True)

# --------------------------------------------
# データ取得
# --------------------------------------------
err_box = st.empty()
try:
    if refresh:
        fetch_predict_latest.clear()
    df_raw = fetch_predict_latest(base_url, n=n)
except Exception as e:
    err_box.error(f"{e}\n\n・APIが起動し `/health` が 200 か確認\n・`base_url` を確認")
    st.stop()

if df_raw is None:
    err_box.error("APIレスポンスの解釈に失敗（df_raw=None）。再取得または Rerun を試してください。")
    st.stop()

if df_raw.empty:
    st.info("データがありません。/api/predict/latest（フォールバック含む）をご確認ください。")
    st.stop()

endpoint_used = st.session_state.get("endpoint_used", "?")
payload_shape = st.session_state.get("payload_shape", "?")

# --------------------------------------------
# サイズ分類（Penny含む）の適用（フォールバックは _compat_bridge でも実施済）
# --------------------------------------------
df_raw = df_raw.copy()

def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None

def _first_value(row, cols):
    for c in cols:
        if c in row.index:
            v = _to_float(row[c])
            if v is not None:
                return v
    return None

price_cols = ["price", "last", "last_price", "close", "adj_close"]
cap_cols   = ["market_cap", "marketcap", "market_capitalization", "mktcap"]

def classify_by_cap_ranges(mc_usd: float, large_min_b: float, mid_min_b: float, mid_max_b: float, small_min_m: float, small_max_m: float) -> str:
    if mc_usd is None:
        return ""
    large_min = large_min_b * 1e9
    mid_min   = mid_min_b   * 1e9
    mid_max   = mid_max_b   * 1e9
    small_min = small_min_m * 1e6
    small_max = small_max_m * 1e6
    if mc_usd >= large_min:
        return "Large"
    if mc_usd >= mid_min and mc_usd < mid_max:
        return "Mid"
    upper_small = min(small_max, mid_min)
    if mc_usd >= small_min and mc_usd < upper_small:
        return "Small"
    if mc_usd < small_min:
        return "Micro"
    if mc_usd < mid_min:
        return "Small"
    return ""

if size_mode != "APIのまま":
    def _size_cap(row):
        mc = _first_value(row, cap_cols)
        if mc is None:
            return row.get("size", "") or ""
        return classify_by_cap_ranges(mc, large_min_b, mid_min_b, mid_max_b, small_min_m, small_max_m)
    df_raw["size"] = df_raw.apply(_size_cap, axis=1)

if size_mode == "時価総額＋ペニー判定":
    method = penny_method or "両方 (どちらか満たす)"
    cap_thresh = (penny_cap_m or 100.0) * 1e6
    px_thresh  = penny_price or 5.0
    label = penny_label or "Penny"

    def _apply_penny(row):
        px = _first_value(row, price_cols)
        mc = _first_value(row, cap_cols)
        by_px = (px is not None and px < px_thresh)
        by_mc = (mc is not None and mc < cap_thresh)
        if method.startswith("株価のみ"):
            is_penny = by_px
        elif method.startswith("時価総額のみ"):
            is_penny = by_mc
        else:
            is_penny = by_px or by_mc
        return label if is_penny else (row.get("size", "") or "")

    df_raw["size"] = df_raw.apply(_apply_penny, axis=1)

# --------------------------------------------
# フィルタ UI（本文側）
# --------------------------------------------
sect_opts = sorted([x for x in df_raw["sector"].dropna().unique().tolist() if x != ""])
band_opts = sorted([x for x in df_raw["time_band"].dropna().unique().tolist() if x != ""])
size_opts = sorted([x for x in df_raw["size"].dropna().unique().tolist() if x != ""])

# 中央のクイック操作（ここに“本文側の”全表示リセットボタンを配置）
btn_col, _ = st.columns([1.8, 8])
with btn_col:
    if st.button("🔁 全表示にリセット", use_container_width=True, key="reset_main"):
        st.session_state["_defer_reset"] = True
        st.rerun()

fcol1, fcol2, fcol3, fcol4 = st.columns([1.3, 1.1, 1.1, 2.0])
with fcol1:
    sect_sel = st.multiselect("セクター", options=sect_opts, default=sect_opts)
with fcol2:
    band_sel = st.multiselect("時間帯", options=band_opts, default=band_opts)
with fcol3:
    size_sel = st.multiselect("サイズ", options=size_opts, default=size_opts)
with fcol4:
    kw = st.text_input("キーワード（symbols, comment 部分一致）", value="")

st.markdown("---")

# --------------------------------------------
# フィルタ適用（ローカル時刻ベース）
# --------------------------------------------
now_local = datetime.now().replace(microsecond=0)
cut = now_local - timedelta(hours=lookback_h)

_df = df_raw.copy()
try:
    _df["dt_local"] = pd.to_datetime(_df["date_local"])
except Exception:
    _df["dt_local"] = pd.NaT

kw_mask = pd.Series([True] * len(_df))
if kw:
    tokens = [t for t in re.split(r"[|\s]+", kw.strip()) if t]
    if tokens:
        sym = _df["symbols"].fillna("").str.lower()
        com = _df["comment"].fillna("").str.lower()
        tok = pd.Series(False, index=_df.index)
        for t in tokens:
            tok |= sym.str.contains(t, case=False, na=False, regex=False)
            tok |= com.str.contains(t, case=False, na=False, regex=False)
        kw_mask = tok

mask = pd.Series([True] * len(_df))
if sect_sel:
    mask &= _df["sector"].isin(sect_sel)
if band_sel:
    mask &= _df["time_band"].isin(band_sel)
if size_sel:
    mask &= _df["size"].isin(size_sel)
mask &= kw_mask
mask &= (_df["dt_local"].isna() | (_df["dt_local"] >= pd.Timestamp(cut)))
if st.session_state["min_conf"] > 0:
    mask &= (_df["confidence"].isna() | (_df["confidence"] >= st.session_state["min_conf"]))
if st.session_state["max_fake"] < 1.0:
    mask &= (_df["fake_rate"].isna() | (_df["fake_rate"] <= st.session_state["max_fake"]))

view = _df.loc[mask].copy()
view = view.sort_values("dt_local", ascending=False, na_position="last")

# --------------------------------------------
# バッジ付与 / 列構築
# --------------------------------------------
view["pred_vol_badge"] = view["pred_vol"].map(lambda v: grade_with_emoji(v, vol_hi, vol_mid, positive_good=False))
view["fake_rate_badge"] = view["fake_rate"].map(lambda v: grade_with_emoji(v, fake_hi, fake_mid, positive_good=False))
view["confidence_badge"] = view["confidence"].map(lambda v: grade_with_emoji(v, conf_hi, conf_mid, positive_good=True))
view["rec_emoji"] = view.apply(lambda r: pick_rec_emoji(r.get("rec_action"), r.get("fake_rate"), r.get("confidence")), axis=1)

view["rec_action"] = view["rec_action"].fillna("").astype(str)
view["rec_emoji"]  = view["rec_emoji"].fillna("").astype(str)
view["rec_display"] = view["rec_emoji"].str.cat(view["rec_action"], sep=" ").str.strip()

for col in ["pred_vol", "fake_rate", "confidence"]:
    view[col] = view[col].map(
        lambda x: None if (x is None or (isinstance(x, float) and math.isnan(x)))
        else max(0.0, min(1.0, float(x)))
    )

show_cols = [
    "date_local", "time_band", "sector", "size",
    "pred_vol_badge", "fake_rate_badge", "confidence_badge",
    "rec_display", "comment", "symbols",
]
for c in show_cols:
    if c not in view.columns:
        view[c] = ""

# --------------------------------------------
# ヘッダ & 凡例
# --------------------------------------------
left, right = st.columns([3, 2])
with left:
    st.subheader("📊 予測サマリー")
    st.caption("絵文字: VOL/FAKE は高いほど🔴注意、CONF は高いほど🟢良い")
with right:
    st.markdown(
        """
        ### 凡例
        **予測ボラ（VOL）**：🟢低 / 🟠中 / 🔴高  
        **だまし率（FAKE）**：🟢低 / 🟠中 / 🔴高  
        **信頼度（CONF）**：🟢高 / 🟠中 / ⚪低
        """
    )

st.write(f"**{len(view)}** 行 — Base: `{base_url}` — 表示範囲: {lookback_h}h — n={n}")
st.caption(f"Endpoint: {st.session_state.get('endpoint_used', '?')}　Payload: {st.session_state.get('payload_shape', '?')}")

# --------------------------------------------
# 出力テーブル
# --------------------------------------------
out = view[show_cols].copy()
st.dataframe(
    out,
    use_container_width=True,
    column_config={
        "date_local": st.column_config.TextColumn("日付(ローカル)", width="medium"),
        "time_band": st.column_config.TextColumn("時間帯", width="small"),
        "sector": st.column_config.TextColumn("セクター", width="small"),
        "size": st.column_config.TextColumn("サイズ", width="small"),
        "pred_vol_badge": st.column_config.TextColumn("予測ボラ", help="0〜1（高いほどボラ大・注意）", width="small"),
        "fake_rate_badge": st.column_config.TextColumn("だまし率", help="0〜1（高いほどダマシ懸念）", width="small"),
        "confidence_badge": st.column_config.TextColumn("信頼度", help="0〜1（高いほど良い）", width="small"),
        "rec_display": st.column_config.TextColumn("推奨", width="small"),
        "comment": st.column_config.TextColumn("コメント", width="large"),
        "symbols": st.column_config.TextColumn("銘柄", width="medium"),
    },
    height=560,
)

# --------------------------------------------
# ダウンロード
# --------------------------------------------
csv = view[[
    "date_local", "time_band", "sector", "size",
    "pred_vol", "fake_rate", "confidence",
    "comment", "rec_action", "symbols",
]].to_csv(index=False)
st.download_button(
    label="⬇️ CSV ダウンロード",
    data=csv,
    file_name=f"predict_view_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)