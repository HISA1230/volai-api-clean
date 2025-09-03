# streamlit_app.py
import io
import os, json, requests, traceback
from urllib.parse import quote
from datetime import datetime, date, time, timedelta
import streamlit as st
from dotenv import load_dotenv
import pandas as pd

load_dotenv()
st.set_page_config(page_title="Volatility AI UI", layout="wide")

# -----------------------------
# API base
# -----------------------------
def get_query_params():
    try:
        return st.query_params
    except Exception:
        return st.experimental_get_query_params()

def get_api_base():
    q = get_query_params()
    if q and ("api" in q) and q["api"]:
        val = q["api"][0] if isinstance(q["api"], list) else q["api"]
        return val.strip().rstrip("/")
    env = os.getenv("API_BASE", "").strip().rstrip("/")
    if env:
        return env
    return "http://127.0.0.1:9999"

API = get_api_base()

def req(method, path, json_data=None, auth=False, timeout=60):
    url = f"{API}{path}"
    headers = {"Content-Type": "application/json"}
    if auth and st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state['token']}"
    r = requests.request(method, url, headers=headers, json=json_data, timeout=timeout)
    r.raise_for_status()
    ctype = (r.headers.get("content-type") or "").lower()
    if ctype.startswith("application/json"):
        return r.json()
    return r.text

# -----------------------------
# Excel bytes（%書式対応）
# -----------------------------
def make_xlsx_bytes(df_or_sheets, *,
                    datetime_format="yyyy-mm-dd hh:mm:ss",
                    date_format="yyyy-mm-dd",
                    percent_cols=None):
    buf = io.BytesIO()
    sheets = df_or_sheets if isinstance(df_or_sheets, dict) else {"Sheet1": df_or_sheets}
    with pd.ExcelWriter(buf, engine="xlsxwriter",
                        datetime_format=datetime_format, date_format=date_format) as writer:
        book = writer.book
        pct_fmt = book.add_format({'num_format': '0.00%'})
        for name, df in sheets.items():
            name = (name or "Sheet1")[:31]
            df = pd.DataFrame(df).copy()
            # tz-aware -> tz-naive
            for c in df.select_dtypes(include=["datetimetz"]).columns:
                df[c] = df[c].dt.tz_convert("UTC").dt.tz_localize(None)
            for c in ("created_at", "updated_at", "ts", "timestamp"):
                if c in df.columns and df[c].dtype == object:
                    df[c] = pd.to_datetime(df[c], utc=True, errors="coerce").dt.tz_localize(None)

            df.to_excel(writer, index=False, sheet_name=name)
            ws = writer.sheets[name]
            # 自動幅 & %書式
            for i, col in enumerate(df.columns):
                try:
                    width = min(60, max(10, int(df[col].astype(str).str.len().max() or 10) + 2))
                except Exception:
                    width = 16
                cell_fmt = pct_fmt if (percent_cols and col in percent_cols) else None
                ws.set_column(i, i, width, cell_fmt)
    return buf.getvalue()

# -----------------------------
# データ取得・整形ヘルパ
# -----------------------------
ORDER = ["id","created_at","sector","size","time_window","pred_vol","abs_error","comment","owner"]
JP_HEADERS = {
    "id":"ID",
    "created_at":"時刻",
    "sector":"セクタ",
    "size":"サイズ",
    "time_window":"時間帯",
    "pred_vol":"予測ボラ",
    "abs_error":"絶対誤差",
    "comment":"コメント",
    "owner":"オーナー",
}
NUM_COLS = ["pred_vol","abs_error"]

def fetch_all_logs(owner: str | None, page_size: int = 1000, max_rows: int = 50000):
    rows, offset = [], 0
    while True:
        path = f"/predict/logs?limit={page_size}&offset={offset}"
        if owner:
            path += f"&owner={quote(owner)}"
        res = req("GET", path, auth=True, timeout=60)
        if not isinstance(res, list):
            raise RuntimeError(f"API error: {res}")
        rows.extend(res)
        if len(res) < page_size or len(rows) >= max_rows:
            break
        offset += page_size
    df = pd.DataFrame(rows)
    for c in ORDER:
        if c not in df.columns:
            df[c] = None
    df = df[ORDER]
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce").dt.tz_localize(None)
    return df.iloc[:max_rows].copy()

def apply_date_filter(df: pd.DataFrame, start: date | None, end: date | None):
    if "created_at" not in df.columns:
        return df
    out = df.copy()
    if start:
        start_dt = datetime.combine(start, datetime.min.time())
        out = out[out["created_at"] >= start_dt]
    if end:
        end_next = datetime.combine(end + timedelta(days=1), datetime.min.time())
        out = out[out["created_at"] < end_next]
    return out

def apply_time_window(df: pd.DataFrame, t_start: time | None, t_end: time | None):
    if "created_at" not in df.columns or not (t_start and t_end):
        return df
    out = df.copy()
    tt = out["created_at"].dt.time
    if t_start <= t_end:
        mask = (tt >= t_start) & (tt <= t_end)
    else:
        # 0時またぎ（例: 22:00〜03:00）
        mask = (tt >= t_start) | (tt <= t_end)
    return out[mask]

def apply_categorical_filters(df: pd.DataFrame, sectors: list[str] | None, sizes: list[str] | None):
    out = df.copy()
    if sectors:
        out = out[out["sector"].isin(sectors)]
    if sizes:
        out = out[out["size"].isin(sizes)]
    return out

def reorder_localize(df: pd.DataFrame, *, use_jp_headers: bool, decimals: int,
                     selected_keys: list[str] | None, show_percent: bool):
    out = df.copy()
    # 列選択 + 既定順
    order = [c for c in ORDER if (not selected_keys or c in selected_keys)]
    for c in order:
        if c not in out.columns:
            out[c] = None
    out = out[order]
    # 数値丸め
    for c in NUM_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            if show_percent:
                out[c] = out[c] * 100.0
            out[c] = out[c].round(decimals)
    # 見出し
    if use_jp_headers:
        out = out.rename(columns=JP_HEADERS)
    return out

# -----------------------------
# セッション状態（初期値）
# -----------------------------
st.session_state.setdefault("token", None)
st.session_state.setdefault("me", None)
st.session_state.setdefault("owner", "共用")
st.session_state.setdefault("models_list", [])

# エクスポート設定
st.session_state.setdefault("exp_start", None)
st.session_state.setdefault("exp_end", None)
st.session_state.setdefault("exp_time_enable", False)
st.session_state.setdefault("exp_time_start", time(0,0))
st.session_state.setdefault("exp_time_end",   time(23,59))
st.session_state.setdefault("exp_max", 5000)
st.session_state.setdefault("exp_jp_headers", True)
st.session_state.setdefault("exp_decimals", 6)
st.session_state.setdefault("exp_columns", ORDER.copy())
st.session_state.setdefault("exp_percent_view", True)      # UI/CSVは%にする
st.session_state.setdefault("exp_percent_in_csv", True)    # CSVも%にする（数値×100）
st.session_state.setdefault("exp_filename_prefix", "logs") # ファイル名の頭

st.markdown("---")
st.markdown("**オーナー固定プリセット（API保存／読込）**")

aa, bb = st.columns(2)

def _current_settings():
    return {
        "start": st.session_state.get("exp_start"),
        "end": st.session_state.get("exp_end"),
        "time_enable": st.session_state.get("exp_time_enable"),
        "time_start": st.session_state.get("exp_time_start"),
        "time_end": st.session_state.get("exp_time_end"),
        "max": st.session_state.get("exp_max"),
        "jp": st.session_state.get("exp_jp_headers"),
        "decimals": st.session_state.get("exp_decimals"),
        "columns": st.session_state.get("exp_columns"),
        "percent_view": st.session_state.get("exp_percent_view"),
        "percent_in_csv": st.session_state.get("exp_percent_in_csv"),
        "prefix": st.session_state.get("exp_filename_prefix"),
        "flt_sectors": st.session_state.get("filter_sectors"),
        "flt_sizes": st.session_state.get("filter_sizes"),
    }

def _apply_settings(s):
    if not isinstance(s, dict):
        return
    from datetime import time
    st.session_state["exp_start"] = s.get("start")
    st.session_state["exp_end"] = s.get("end")
    st.session_state["exp_time_enable"] = s.get("time_enable", False)
    st.session_state["exp_time_start"]  = s.get("time_start", time(0,0))
    st.session_state["exp_time_end"]    = s.get("time_end", time(23,59))
    st.session_state["exp_max"] = s.get("max", 5000)
    st.session_state["exp_jp_headers"] = s.get("jp", True)
    st.session_state["exp_decimals"] = s.get("decimals", 6)
    st.session_state["exp_columns"] = s.get("columns", st.session_state.get("exp_columns"))
    st.session_state["exp_percent_view"] = s.get("percent_view", True)
    st.session_state["exp_percent_in_csv"] = s.get("percent_in_csv", True)
    st.session_state["exp_filename_prefix"] = s.get("prefix", "logs")
    st.session_state["filter_sectors"] = s.get("flt_sectors", [])
    st.session_state["filter_sizes"] = s.get("flt_sizes", [])

with aa:
    if st.button("この設定をオーナー既定として保存（API）", use_container_width=True, disabled=not st.session_state.get("token")):
        try:
            body = {
                "owner": st.session_state["owner"] or "共用",
                "params": { "ui_export_defaults": _current_settings() }
            }
            res = req("POST", "/owners/settings", body, auth=True, timeout=30)
            st.success("サーバに保存しました（/owners/settings）")
        except Exception as e:
            st.error(f"保存失敗: {e}")
            st.code(traceback.format_exc())

with bb:
    if st.button("サーバ保存の既定を読み込み（API）", use_container_width=True, disabled=not st.session_state.get("token")):
        try:
            o = st.session_state["owner"] or "共用"
            res = req("GET", f"/owners/settings?owner={quote(o)}", auth=True, timeout=20)
            s = (res.get("params") or {}).get("ui_export_defaults")
            if s:
                _apply_settings(s)
                st.success("サーバ保存の既定を適用しました")
            else:
                st.info("サーバ側に保存された既定が見つかりませんでした")
        except Exception as e:
            st.error(f"読込失敗: {e}")
            st.code(traceback.format_exc())

# フィルタ候補 & 値
st.session_state.setdefault("filter_sector_choices", [])
st.session_state.setdefault("filter_size_choices", [])
st.session_state.setdefault("filter_sectors", [])
st.session_state.setdefault("filter_sizes", [])

# プリセット（セッション内）
st.session_state.setdefault("presets", {})  # {owner: { ...settings... }}

# -----------------------------
# ヘッダ & 認証
# -----------------------------
st.title("Volatility AI - Minimal UI")
st.caption(f"API Base: **{API}** | Swagger: {API}/docs")

with st.sidebar:
    st.subheader("ログイン")
    default_email = os.getenv("API_EMAIL", "test@example.com")
    default_pass  = os.getenv("API_PASSWORD", "test1234")
    email = st.text_input("Email", value=default_email)
    password = st.text_input("Password", type="password", value=default_pass)

    cA, cB = st.columns(2)
    if cA.button("ログイン"):
        try:
            data = req("POST", "/login", {"email": email, "password": password}, auth=False, timeout=30)
            st.session_state["token"] = data["access_token"]
            st.session_state["me"] = req("GET", "/me", auth=True, timeout=30)
            st.success(f"ログイン成功: {st.session_state['me']['email']}")
        except Exception as e:
            st.error(f"ログイン失敗: {e}")
            st.code(traceback.format_exc())
    if cB.button("新規登録"):
        try:
            me = req("POST", "/register", {"email": email, "password": password}, auth=False, timeout=30)
            st.success(f"登録成功: {me['email']} → 続けてログインを押してください")
        except Exception as e:
            st.error(f"登録失敗: {e}")
            st.code(traceback.format_exc())
    if st.session_state.get("token") and st.button("ログアウト"):
        st.session_state["token"] = None
        st.session_state["me"] = None
        st.info("ログアウトしました")

    st.divider()
    st.subheader("オーナー")
    owners = ["共用","学也","正恵","練習H","練習M"]
    if st.session_state.get("token"):
        try:
            api_owners = req("GET", "/owners", auth=True, timeout=20)
            if isinstance(api_owners, list) and api_owners:
                owners = [o for o in api_owners if o and o != "??"]
        except Exception as e:
            st.caption("owners の取得にはログインが必要です")
            st.caption(str(e))
    if st.session_state["owner"] not in owners:
        st.session_state["owner"] = "共用" if "共用" in owners else owners[0]
    st.selectbox("Owner", owners, index=owners.index(st.session_state["owner"]), key="owner")

# -----------------------------
# エクスポート設定（期間・列・書式・フィルタ・順序）
# -----------------------------
with st.expander("エクスポート設定（期間・列・書式・フィルタ・並び）", expanded=False):
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    with r1c1:
        st.session_state["exp_start"] = st.date_input("開始日", value=st.session_state.get("exp_start"))
    with r1c2:
        st.session_state["exp_end"] = st.date_input("終了日", value=st.session_state.get("exp_end"))
    with r1c3:
        st.session_state["exp_time_enable"] = st.checkbox("時刻帯で絞る", value=bool(st.session_state.get("exp_time_enable")))
        st.session_state["exp_time_start"]  = st.time_input("開始時刻", value=st.session_state.get("exp_time_start", time(0,0)))
        st.session_state["exp_time_end"]    = st.time_input("終了時刻", value=st.session_state.get("exp_time_end", time(23,59)))
    with r1c4:
        st.session_state["exp_max"] = st.number_input("最大行数", min_value=100, max_value=100000,
                                                      value=int(st.session_state.get("exp_max", 5000)), step=100)

    r2c1, r2c2, r2c3, r2c4 = st.columns([2,1,1,1])
    with r2c1:
        st.markdown("**列の選択**")
        st.session_state["exp_columns"] = st.multiselect(
            "英名で選択（出力時は日本語見出しに変換可）",
            ORDER,
            default=st.session_state.get("exp_columns", ORDER),
        )
        # 並び替え（▲▼）
        st.caption("並び替え（▲▼ボタンで移動）")
        cols = st.session_state["exp_columns"] or []
        btn_cols = st.columns(3)
        for i, c in enumerate(cols):
            bc1, bc2, bc3 = st.columns([0.1, 0.1, 0.8])
            up = bc1.button("▲", key=f"up_{c}", help="上へ")
            down = bc2.button("▼", key=f"down_{c}", help="下へ")
            bc3.write(c)
            if up and i > 0:
                cols[i-1], cols[i] = cols[i], cols[i-1]
                st.session_state["exp_columns"] = cols
                st.rerun()
            if down and i < len(cols)-1:
                cols[i+1], cols[i] = cols[i], cols[i+1]
                st.session_state["exp_columns"] = cols
                st.rerun()

    with r2c2:
        st.markdown("**小数点桁数**")
        st.session_state["exp_decimals"] = st.number_input("pred_vol / abs_error", min_value=0, max_value=10,
                                                           value=int(st.session_state.get("exp_decimals", 6)), step=1)
    with r2c3:
        st.session_state["exp_jp_headers"] = st.checkbox("日本語見出し", value=bool(st.session_state.get("exp_jp_headers", True)))
        st.session_state["exp_percent_view"] = st.checkbox("UI/CSV を百分率で表示", value=bool(st.session_state.get("exp_percent_view", True)))
        st.session_state["exp_percent_in_csv"] = st.checkbox("CSVにも百分率を出力", value=bool(st.session_state.get("exp_percent_in_csv", True)))
    with r2c4:
        st.text_input("ファイル名プリフィクス", key="exp_filename_prefix")

    r3c1, r3c2, r3c3 = st.columns([2,1,1])
    with r3c1:
        st.markdown("**フィルタ候補更新（選択オーナー）**")
        if st.button("候補を更新", use_container_width=True, disabled=not st.session_state.get("token")):
            try:
                tmp = fetch_all_logs(st.session_state["owner"], page_size=1000, max_rows=10000)
                tmp = apply_date_filter(tmp, st.session_state["exp_start"], st.session_state["exp_end"])
                if st.session_state["exp_time_enable"]:
                    tmp = apply_time_window(tmp, st.session_state["exp_time_start"], st.session_state["exp_time_end"])
                st.session_state["filter_sector_choices"] = sorted([x for x in tmp["sector"].dropna().unique().tolist() if x != ""])
                st.session_state["filter_size_choices"]   = sorted([x for x in tmp["size"].dropna().unique().tolist() if x != ""])
                st.success(f"候補更新 OK（sectors={len(st.session_state['filter_sector_choices'])}, sizes={len(st.session_state['filter_size_choices'])}）")
            except Exception as e:
                st.error(f"候補更新失敗: {e}")
    with r3c2:
        st.markdown("**セクタ**")
        st.session_state["filter_sectors"] = st.multiselect(
            "含めるセクタ（空=全件）",
            st.session_state.get("filter_sector_choices", []),
            default=st.session_state.get("filter_sectors", []),
        )
    with r3c3:
        st.markdown("**サイズ**")
        st.session_state["filter_sizes"] = st.multiselect(
            "含めるサイズ（空=全件）",
            st.session_state.get("filter_size_choices", []),
            default=st.session_state.get("filter_sizes", []),
        )

    st.markdown("---")
    st.markdown("**プリセット**（このセッション内 / JSON入出力）")
    p1, p2, p3, p4 = st.columns(4)

    def _current_settings():
        return {
            "start": st.session_state.get("exp_start"),
            "end": st.session_state.get("exp_end"),
            "time_enable": st.session_state.get("exp_time_enable"),
            "time_start": st.session_state.get("exp_time_start"),
            "time_end": st.session_state.get("exp_time_end"),
            "max": st.session_state.get("exp_max"),
            "jp": st.session_state.get("exp_jp_headers"),
            "decimals": st.session_state.get("exp_decimals"),
            "columns": st.session_state.get("exp_columns"),
            "percent_view": st.session_state.get("exp_percent_view"),
            "percent_in_csv": st.session_state.get("exp_percent_in_csv"),
            "prefix": st.session_state.get("exp_filename_prefix"),
            "flt_sectors": st.session_state.get("filter_sectors"),
            "flt_sizes": st.session_state.get("filter_sizes"),
        }

    def _apply_settings(s):
        if not isinstance(s, dict): return
        st.session_state["exp_start"] = s.get("start")
        st.session_state["exp_end"] = s.get("end")
        st.session_state["exp_time_enable"] = s.get("time_enable", False)
        st.session_state["exp_time_start"]  = s.get("time_start", time(0,0))
        st.session_state["exp_time_end"]    = s.get("time_end", time(23,59))
        st.session_state["exp_max"] = s.get("max", 5000)
        st.session_state["exp_jp_headers"] = s.get("jp", True)
        st.session_state["exp_decimals"] = s.get("decimals", 6)
        st.session_state["exp_columns"] = s.get("columns", ORDER)
        st.session_state["exp_percent_view"] = s.get("percent_view", True)
        st.session_state["exp_percent_in_csv"] = s.get("percent_in_csv", True)
        st.session_state["exp_filename_prefix"] = s.get("prefix", "logs")
        st.session_state["filter_sectors"] = s.get("flt_sectors", [])
        st.session_state["filter_sizes"] = s.get("flt_sizes", [])

    with p1:
        if st.button("現在の設定を保存（このオーナーに）"):
            owner = st.session_state["owner"]
            st.session_state["presets"][owner] = _current_settings()
            st.success(f"保存しました（{owner}）")

    with p2:
        if st.button("保存済みを適用（このオーナー）"):
            owner = st.session_state["owner"]
            s = st.session_state["presets"].get(owner)
            if s: _apply_settings(s); st.success(f"適用しました（{owner}）")
            else: st.info("保存済みプリセットがありません")

    with p3:
        # JSON ダウンロード
        preset_json = json.dumps(_current_settings(), ensure_ascii=False, default=str, indent=2)
        st.download_button("JSONダウンロード", data=preset_json.encode("utf-8"),
                           file_name=f"preset_{st.session_state['owner']}.json", mime="application/json")

    with p4:
        up = st.file_uploader("JSON読み込み", type=["json"], label_visibility="collapsed")
        if up:
            try:
                s = json.loads(up.read().decode("utf-8"))
                _apply_settings(s)
                st.success("プリセットを適用しました")
            except Exception as e:
                st.error(f"読込失敗: {e}")

# 使い回しの設定値を取り出し
start_date = st.session_state.get("exp_start")
end_date   = st.session_state.get("exp_end")
max_rows   = int(st.session_state.get("exp_max", 5000))
use_jp     = bool(st.session_state.get("exp_jp_headers", True))
decimals   = int(st.session_state.get("exp_decimals", 6))
sel_cols   = st.session_state.get("exp_columns", ORDER)
show_pct   = bool(st.session_state.get("exp_percent_view", True))
csv_pct    = bool(st.session_state.get("exp_percent_in_csv", True))
prefix     = (st.session_state.get("exp_filename_prefix") or "logs").strip() or "logs"
t_enable   = bool(st.session_state.get("exp_time_enable", False))
t_start    = st.session_state.get("exp_time_start", time(0,0))
t_end      = st.session_state.get("exp_time_end", time(23,59))
flt_secs   = st.session_state.get("filter_sectors", [])
flt_sizes  = st.session_state.get("filter_sizes", [])

# -----------------------------
# メイン操作
# -----------------------------
st.divider()
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Health確認"):
        try:
            h = req("GET", "/health", auth=False, timeout=15)
            st.json(h)
        except Exception as e:
            st.error(e)
with c2:
    if st.button("ログ一覧（選択オーナー表示・期間/時刻/フィルタ反映）"):
        try:
            df = fetch_all_logs(st.session_state["owner"], page_size=1000, max_rows=max_rows)
            df = apply_date_filter(df, start_date, end_date)
            if t_enable:
                df = apply_time_window(df, t_start, t_end)
            df = apply_categorical_filters(df, flt_secs, flt_sizes)
            df_out = reorder_localize(df, use_jp_headers=use_jp, decimals=decimals,
                                      selected_keys=sel_cols, show_percent=show_pct)
            st.write(f"Owner: **{st.session_state['owner']}** / 件数: {len(df_out)}")
            st.dataframe(df_out.head(50))
        except Exception as e:
            st.error(e)
            st.info("※トークンが必要です。左でログインしてください。")
with c3:
    if st.button("SHAP再計算（ダミー）"):
        try:
            res = req("POST", "/predict/shap/recompute", auth=True, timeout=180)
            st.success("SHAP再計算OK（ダミー）")
            st.json(res)
        except Exception as e:
            st.error(e)

# -----------------------------
# CSV ダウンロード
# -----------------------------
st.divider()
with st.expander("CSVダウンロード（UTF-8 BOM付き）", expanded=False):
    col_dl1, col_dl2 = st.columns(2)

    def _prep_df(owner: str | None):
        df = fetch_all_logs(owner, page_size=1000, max_rows=max_rows)
        df = apply_date_filter(df, start_date, end_date)
        if t_enable:
            df = apply_time_window(df, t_start, t_end)
        df = apply_categorical_filters(df, flt_secs, flt_sizes)
        return df

    with col_dl1:
        if st.button("選択オーナーの全ログ（CSV）を準備"):
            try:
                o  = st.session_state["owner"] or "共用"
                df = _prep_df(o)
                df_out = reorder_localize(df, use_jp_headers=use_jp, decimals=decimals,
                                          selected_keys=sel_cols, show_percent=csv_pct)
                st.success(f"{o} のログ {len(df_out)} 行を準備しました")
                csv = df_out.to_csv(index=False, encoding="utf-8-sig")
                fname = f"{prefix}_{o}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                st.download_button("CSVをダウンロード", data=csv, file_name=fname, mime="text/csv")
                st.dataframe(df_out.head(20))
            except Exception as e:
                st.error(f"準備失敗: {e}")
                st.code(traceback.format_exc())

    with col_dl2:
        if st.button("全オーナーの全ログ（CSV）を準備"):
            try:
                df = _prep_df(None)
                df_out = reorder_localize(df, use_jp_headers=use_jp, decimals=decimals,
                                          selected_keys=sel_cols, show_percent=csv_pct)
                st.success(f"全オーナーのログ {len(df_out)} 行を準備しました")
                csv = df_out.to_csv(index=False, encoding="utf-8-sig")
                fname = f"{prefix}_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                st.download_button("CSVをダウンロード", data=csv, file_name=fname, mime="text/csv")
                st.dataframe(df_out.head(20))
            except Exception as e:
                st.error(f"準備失敗: {e}")
                st.code(traceback.format_exc())

# -----------------------------
# Excel ダウンロード（%書式）
# -----------------------------
st.divider()
st.subheader("Excel ダウンロード（.xlsx）")
ex1, ex2, ex3 = st.columns(3)

def _excel_df(owner: str | None):
    df = fetch_all_logs(owner, page_size=1000, max_rows=max_rows)
    df = apply_date_filter(df, start_date, end_date)
    if t_enable:
        df = apply_time_window(df, t_start, t_end)
    df = apply_categorical_filters(df, flt_secs, flt_sizes)
    # Excel では%書式を列に適用するので、データ自体は「小数のまま」（show_percent=False）
    df_out = reorder_localize(df, use_jp_headers=use_jp, decimals=decimals,
                              selected_keys=sel_cols, show_percent=False)
    # 書式を当てる列名（日本語見出しにしている場合は日本語名で指定）
    pct_cols = [JP_HEADERS[c] if use_jp else c for c in NUM_COLS if (JP_HEADERS[c] if use_jp else c) in df_out.columns]
    return df_out, pct_cols

with ex1:
    if st.button("選択オーナーの全ログを .xlsx"):
        try:
            o  = st.session_state.get("owner") or "共用"
            df_out, pct_cols = _excel_df(o)
            data = make_xlsx_bytes(df_out, percent_cols=pct_cols)
            st.download_button("ダウンロード（xlsx）", data=data,
                               file_name=f"{prefix}_{o}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(e)

with ex2:
    if st.button("全オーナーの全ログを .xlsx"):
        try:
            df_out, pct_cols = _excel_df(None)
            data = make_xlsx_bytes(df_out, percent_cols=pct_cols)
            st.download_button("ダウンロード（xlsx）", data=data,
                               file_name=f"{prefix}_all.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(e)

with ex3:
    if st.button("サマリー（owner/sector/size）を .xlsx"):
        try:
            sheets = {}
            s_owner = req("GET", "/predict/logs/summary?by=owner", auth=True, timeout=20)
            sheets["by_owner"] = pd.DataFrame(s_owner)
            o = st.session_state.get("owner") or "共用"
            s_sector = req("GET", f"/predict/logs/summary?owner={quote(o)}&by=sector", auth=True, timeout=20)
            s_size   = req("GET", f"/predict/logs/summary?owner={quote(o)}&by=size", auth=True, timeout=20)
            sheets[f"{o}_by_sector"] = pd.DataFrame(s_sector)
            sheets[f"{o}_by_size"]   = pd.DataFrame(s_size)
            data = make_xlsx_bytes(sheets)
            st.download_button("ダウンロード（xlsx）", data=data,
                               file_name=f"{prefix}_summary_{o}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(e)
            
st.divider()
st.subheader("可視化（現在のフィルタを反映）")

viz_owner = st.session_state["owner"] or "共用"
if st.button("再集計（選択オーナー）"):
    try:
        df = fetch_all_logs(viz_owner, page_size=1000, max_rows=int(st.session_state.get("exp_max", 5000)))
        df = apply_date_filter(df, st.session_state.get("exp_start"), st.session_state.get("exp_end"))
        if st.session_state.get("exp_time_enable"):
            df = apply_time_window(df, st.session_state.get("exp_time_start"), st.session_state.get("exp_time_end"))
        df = apply_categorical_filters(df, st.session_state.get("filter_sectors", []), st.session_state.get("filter_sizes", []))
        st.session_state["_viz_df"] = df
        st.success(f"再集計 OK（{len(df)} 行）")
    except Exception as e:
        st.error(e)

dfv = st.session_state.get("_viz_df")
if isinstance(dfv, pd.DataFrame) and not dfv.empty:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**セクタ別件数**")
        vc = dfv["sector"].fillna("(NA)").value_counts().sort_values(ascending=False)
        st.bar_chart(vc)

    with c2:
        st.markdown("**サイズ別件数**")
        vs = dfv["size"].fillna("(NA)").value_counts().sort_values(ascending=False)
        st.bar_chart(vs)

    st.markdown("**セクタ × 時刻（時） ヒートマップ**")
    try:
        tmp = dfv.copy()
        tmp["hour"] = tmp["created_at"].dt.hour
        pv = pd.pivot_table(tmp, index="sector", columns="hour", values="id", aggfunc="count", fill_value=0)
        pv = pv.sort_index()
        # ヒートマップ（matplotlib）
        import matplotlib.pyplot as plt
        import numpy as np
        fig, ax = plt.subplots(figsize=(10, max(3, len(pv.index)*0.35)))
        im = ax.imshow(pv.values, aspect="auto")
        ax.set_yticks(np.arange(len(pv.index)), labels=pv.index)
        ax.set_xticks(np.arange(len(pv.columns)), labels=pv.columns)
        ax.set_xlabel("Hour")
        ax.set_ylabel("Sector")
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        st.pyplot(fig, clear_figure=True)
    except Exception as e:
        st.info("ヒートマップを描画できませんでした。データ件数や列名をご確認ください。")
        st.caption(str(e))
else:
    st.caption("上の『再集計（選択オーナー）』を押すと、ここにグラフが出ます。")

# -----------------------------
# 現在のユーザー
# -----------------------------
st.divider()
st.subheader("現在のユーザー")
if st.session_state.get("me"):
    st.json(st.session_state["me"])
else:
    st.write("未ログイン")