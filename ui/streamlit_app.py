# -*- coding: utf-8 -*-
"""
Streamlit UI — 見栄え仕上げ v1（互換ブリッジ対応）
- 固定列: 日付(ローカル) / 時間帯 / セクター / サイズ / 予測ボラ / だまし率 / 信頼度 / コメント / 推奨
- 絵文字バッジ & フィルタ付き
- /api/predict/latest が 404 の場合は /api/strategy/latest にフォールバックし、
  旧カラムを新スキーマにマッピングして表示
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
st.set_page_config(
    page_title="Volatility AI — Predict View",
    page_icon="📈",
    layout="wide",
)

# ---- デバッグ表示（一時的）----
import pathlib
st.sidebar.success("UI tag: predict-view v1 🧩")
st.sidebar.caption(f"Loaded file: {pathlib.Path(__file__).resolve()}")

# --------------------------------------------
# ユーティリティ
# --------------------------------------------
def _parse_num(x: Any) -> Optional[float]:
    """'0.62 🟢' のような文字から数値を抽出"""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"[-+]?[0-9]*\.?[0-9]+", str(x))
    return float(m.group(0)) if m else None


def _compat_bridge(df: pd.DataFrame) -> pd.DataFrame:
    """
    旧API（/api/strategy/latest）由来の日本語カラムを
    新スキーマ（/api/predict/latest 相当）にマッピングする暫定ブリッジ
    旧: 時刻, セクター, 窓[h], 平均スコア(色), ポジ比率, ボリューム, 銘柄
    新: ts_utc, sector, time_band, pred_vol, confidence, (fake_rate=None), symbols
    """
    if not {"時刻", "セクター"}.issubset(set(df.columns)):
        return df  # 旧形式でなければ何もしない

    df = df.copy()
    df.rename(columns={
        "時刻": "ts_utc",
        "セクター": "sector",
        "銘柄": "symbols",
    }, inplace=True)

    # time_band は「窓[h]」を文字にして代用（なければ空）
    if "窓[h]" in df.columns:
        df["time_band"] = df["窓[h]"].apply(lambda v: f"{v}h" if v not in (None, "") else "")
    else:
        df["time_band"] = ""

    # pred_vol ← 平均スコア(色) から数値抽出
    if "平均スコア(色)" in df.columns and "pred_vol" not in df.columns:
        df["pred_vol"] = df["平均スコア(色)"].map(_parse_num)

    # confidence ← ポジ比率 から数値抽出
    if "ポジ比率" in df.columns and "confidence" not in df.columns:
        df["confidence"] = df["ポジ比率"].map(_parse_num)

    # fake_rate は旧データに存在しない想定なので None
    if "fake_rate" not in df.columns:
        df["fake_rate"] = None

    # size は旧データに対応なし → 空文字
    if "size" not in df.columns:
        df["size"] = ""

    return df


@st.cache_data(show_spinner=False, ttl=15)
def fetch_predict_latest(base: str, n: int = 200) -> pd.DataFrame:
    """
    /api/predict/latest を優先して取得。
    404 の場合は /api/strategy/latest にフォールバックし、互換ブリッジを適用。
    取得後は最低限の整形（ts_utc → ローカル時刻、symbols 正規化など）を行う。
    """
    predict_url = f"{base.rstrip('/')}/api/predict/latest"
    strat_url   = f"{base.rstrip('/')}/api/strategy/latest"

    used = None
    data: list[dict] = []

    # 1) 新APIを試す
    try:
        r = requests.get(predict_url, params={"n": n}, timeout=10)
        if r.status_code == 404:
            raise requests.HTTPError("404 on /api/predict/latest", response=r)
        r.raise_for_status()
        data = r.json() or []
        used = "/api/predict/latest"
    except Exception as e1:
        # 2) 旧APIにフォールバック
        try:
            r = requests.get(strat_url, params={"n": n}, timeout=10)
            r.raise_for_status()
            data = r.json() or []
            used = "/api/strategy/latest"
        except Exception as e2:
            raise RuntimeError(
                f"API 呼び出しに失敗: {predict_url} / {strat_url}\n- {e1}\n- {e2}"
            )

    st.session_state["endpoint_used"] = used

    if not isinstance(data, list):
        raise RuntimeError("API 返却がリスト形式ではありません")

    df = pd.DataFrame(data)
    # 旧形式なら新形式へマッピング
    df = _compat_bridge(df)

    if df.empty:
        return df

    # 欠損カラムを補完
    for col in [
        "ts_utc", "time_band", "sector", "size",
        "pred_vol", "fake_rate", "confidence",
        "comment", "rec_action", "symbols",
    ]:
        if col not in df.columns:
            df[col] = None

    # ts_utc → ローカル文字列
    def to_local(ts: Any) -> str:
        if ts in (None, "", float("nan")):
            return ""
        try:
            s = pd.to_datetime(ts, utc=True, errors="coerce")
            if pd.isna(s):
                return str(ts)
            # ローカルタイムに変換して文字列化
            s_local = s.tz_convert(tz=None)
            return s_local.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)

    df["date_local"] = df["ts_utc"].map(to_local)

    # symbols が配列ならカンマ区切り文字列に
    def norm_symbols(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, list):
            return ", ".join(map(str, v))
        return str(v)

    df["symbols"] = df["symbols"].map(norm_symbols)

    # 数値化（None/NaN 安全）
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
    """絵文字バッジを返す（positive_good=True は高いほど良い）"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "▫️ N/A"

    if positive_good:
        if value >= hi:
            return f"🟢 {value:.2f}"
        elif value >= mid:
            return f"🟠 {value:.2f}"
        else:
            return f"⚪ {value:.2f}"
    else:
        if value >= hi:
            return f"🔴 {value:.2f}"
        elif value >= mid:
            return f"🟠 {value:.2f}"
        else:
            return f"🟢 {value:.2f}"


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
    base_url = st.text_input("API Base URL", value=default_base, help="例: http://127.0.0.1:8021")

    n = st.slider("取得件数 (n)", 20, 1000, 200, step=20)
    lookback_h = st.slider("直近だけ表示 (hours)", 1, 168, 48)

    st.markdown("---")
    st.caption("しきい値（バックエンドと揃える）")
    col1, col2 = st.columns(2)
    with col1:
        vol_hi = st.number_input("VOL: High ≥", value=0.70, min_value=0.0, max_value=1.0, step=0.05)
        vol_mid = st.number_input("VOL: Mid ≥", value=0.40, min_value=0.0, max_value=1.0, step=0.05)
        fake_hi = st.number_input("FAKE: High ≥", value=0.60, min_value=0.0, max_value=1.0, step=0.05)
        fake_mid = st.number_input("FAKE: Mid ≥", value=0.30, min_value=0.0, max_value=1.0, step=0.05)
    with col2:
        conf_hi = st.number_input("CONF: High ≥", value=0.70, min_value=0.0, max_value=1.0, step=0.05)
        conf_mid = st.number_input("CONF: Mid ≥", value=0.40, min_value=0.0, max_value=1.0, step=0.05)
        min_conf = st.slider("絞り込み: 最低信頼度", 0.0, 1.0, 0.0, 0.05)
        max_fake = st.slider("絞り込み: 最大だまし率", 0.0, 1.0, 1.0, 0.05)

    st.markdown("---")
    refresh = st.button("🔄 再取得 / Refresh")

# --------------------------------------------
# データ取得
# --------------------------------------------
err_box = st.empty()
try:
    if refresh:
        fetch_predict_latest.clear()
    df_raw = fetch_predict_latest(base_url, n=n)
except Exception as e:
    err_box.error(f"{e}\n\n・APIが起動し `/health` が 200 か確認してください\n・`base_url` が正しいか確認してください")
    st.stop()

endpoint_used = st.session_state.get("endpoint_used", "?")
st.sidebar.info(f"Endpoint used: {endpoint_used}")

# 空なら終了
if df_raw.empty:
    st.info("データがありません。/api/predict/latest（または互換フォールバック）を確認してください。")
    st.stop()

# --------------------------------------------
# フィルタUI（データに基づく選択肢）
# --------------------------------------------
sect_opts = sorted([x for x in df_raw["sector"].dropna().unique().tolist() if x != ""])
band_opts = sorted([x for x in df_raw["time_band"].dropna().unique().tolist() if x != ""])
size_opts = sorted([x for x in df_raw["size"].dropna().unique().tolist() if x != ""])

fcol1, fcol2, fcol3, fcol4 = st.columns([1.3, 1.1, 1.1, 2.0])
with fcol1:
    sect_sel = st.multiselect("セクター", options=sect_opts, default=sect_opts)
with fcol2:
    band_sel = st.multiselect("時間帯", options=band_opts, default=band_opts)
with fcol3:
    size_sel = st.multiselect("サイズ", options=size_opts, default=size_opts)
with fcol4:
    kw = st.text_input("キーワード（symbols, comment 部分一致）", value="")

# --------------------------------------------
# フィルタ適用
# --------------------------------------------
now_local = datetime.now().replace(microsecond=0)
cut = now_local - timedelta(hours=lookback_h)

_df = df_raw.copy()
try:
    _df["dt_local"] = pd.to_datetime(_df["date_local"])
except Exception:
    _df["dt_local"] = pd.NaT

mask = pd.Series([True] * len(_df))
if sect_sel:
    mask &= _df["sector"].isin(sect_sel)
if band_sel:
    mask &= _df["time_band"].isin(band_sel)
if size_sel:
    mask &= _df["size"].isin(size_sel)
mask &= (_df["dt_local"].isna() | (_df["dt_local"] >= pd.Timestamp(cut)))
if min_conf > 0:
    mask &= (_df["confidence"].isna() | (_df["confidence"] >= min_conf))
if max_fake < 1.0:
    mask &= (_df["fake_rate"].isna() | (_df["fake_rate"] <= max_fake))
if kw:
    kw_low = kw.lower()
    mask &= (
        _df["symbols"].fillna("").str.lower().str.contains(kw_low)
        | _df["comment"].fillna("").str.lower().str.contains(kw_low)
    )

view = _df.loc[mask].copy()

# --------------------------------------------
# バッジ付与 / 表示列の構築
# --------------------------------------------
view["pred_vol_badge"] = view["pred_vol"].map(lambda v: grade_with_emoji(v, vol_hi, vol_mid, positive_good=False))
view["fake_rate_badge"] = view["fake_rate"].map(lambda v: grade_with_emoji(v, fake_hi, fake_mid, positive_good=False))
view["confidence_badge"] = view["confidence"].map(lambda v: grade_with_emoji(v, conf_hi, conf_mid, positive_good=True))
view["rec_emoji"] = view.apply(lambda r: pick_rec_emoji(r.get("rec_action"), r.get("fake_rate"), r.get("confidence")), axis=1)

# 数値域の安全化（0〜1にクリップ）
for col in ["pred_vol", "fake_rate", "confidence"]:
    view[col] = view[col].map(
        lambda x: None if (x is None or (isinstance(x, float) and math.isnan(x)))
        else max(0.0, min(1.0, float(x)))
    )

# 欲しい列順（固定）
show_cols = [
    "date_local", "time_band", "sector", "size",
    "pred_vol_badge", "fake_rate_badge", "confidence_badge",
    "comment", "rec_action", "symbols",
]
for c in show_cols:
    if c not in view.columns:
        view[c] = ""

# ヘッダ & レジェンド
left, right = st.columns([3, 2])
with left:
    st.subheader("📊 予測サマリー")
    st.caption("絵文字: VOL/FAKE は高いほど🔴注意、CONF は高いほど🟢良い")
with right:
    st.markdown(
        """
        **Legend**  
        VOL: 🟢低 / 🟠中 / 🔴高  
        FAKE: 🟢低 / 🟠中 / 🔴高  
        CONF: 🟢高 / 🟠中 / ⚪低
        """
    )

# 統計の一言
st.write(
    f"**{len(view)}** rows — Base: `{base_url}` — Endpoint: **{endpoint_used}** / "
    f"Lookback: {lookback_h}h — n={n}"
)

# 出力テーブル
out = view[show_cols].copy()
st.dataframe(
    out,
    use_container_width=True,
    column_config={
        "date_local": st.column_config.TextColumn("日付(ローカル)", width="medium"),
        "time_band": st.column_config.TextColumn("時間帯", width="small"),
        "sector": st.column_config.TextColumn("セクター", width="small"),
        "size": st.column_config.TextColumn("サイズ", width="small"),
        "pred_vol_badge": st.column_config.TextColumn("予測ボラ", help="VOL: 0-1 (高いほどボラ大・注意)", width="small"),
        "fake_rate_badge": st.column_config.TextColumn("だまし率", help="FAKE: 0-1 (高いほどダマシ懸念)", width="small"),
        "confidence_badge": st.column_config.TextColumn("信頼度", help="CONF: 0-1 (高いほど良い)", width="small"),
        "comment": st.column_config.TextColumn("コメント", width="large"),
        "rec_action": st.column_config.TextColumn("推奨", width="small"),
        "symbols": st.column_config.TextColumn("銘柄", width="medium"),
    },
    height=560,
)

# ダウンロード
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

st.caption("Tips: 表示が古いときはサイドバーの『再取得』、もしくは Streamlit のメニューから Clear cache → Rerun。")