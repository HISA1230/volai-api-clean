# pages/02_Scheduler.py
import os
from datetime import datetime
import requests
import streamlit as st

st.set_page_config(page_title="Scheduler", page_icon="⏱️", layout="wide", initial_sidebar_state="expanded")
st.title("⏱️ スケジューラ（ドライラン / 本番）")

# -----------------------------
# API Base の自動入力＆保持
# 優先度: ?api=... > session > secrets > env > 既定
# -----------------------------
def _get_query_api():
    try:
        qp = st.query_params  # >=1.30
        return qp.get("api")
    except Exception:
        qp = st.experimental_get_query_params()
        return qp.get("api", [None])[0]

def _set_query_api(val: str):
    try:
        st.query_params["api"] = val
    except Exception:
        st.experimental_set_query_params(api=val)

def _get_secrets_api():
    # secrets.toml が無い/読めない場合は None を返す
    try:
        return st.secrets["API_BASE"]
    except Exception:
        return None

api_from_url     = _get_query_api()
api_from_state   = st.session_state.get("api_base")
api_from_secrets = _get_secrets_api()
api_from_env     = os.getenv("API_BASE")

api_base = api_from_url or api_from_state or api_from_secrets or api_from_env or "http://127.0.0.1:8888"
api_base = api_base.rstrip("/")
st.session_state["api_base"] = api_base
_set_query_api(api_base)  # URL に保存（ブックマークで次回自動復元）

def _u(path: str) -> str:
    return f"{api_base}{path}"

# -----------------------------
# サイドバー：接続＆ログイン
# -----------------------------
with st.sidebar:
    st.subheader("接続設定")
    api_base = st.text_input("API Base", value=api_base, help="例: https://xxxxx.trycloudflare.com").rstrip("/")
    st.session_state["api_base"] = api_base
    _set_query_api(api_base)

    # 簡易ヘルスチェック
    ok, msg = False, ""
    try:
        r = requests.get(_u("/"), timeout=6)
        ok = r.ok
        msg = (r.text or "")[:120]
    except Exception as e:
        msg = f"ping error: {e}"
    st.write("API疎通:", "🟢 OK" if ok else "🔴 NG")
    st.caption(msg)

    st.subheader("ログイン")
    EMAIL_DEFAULT = "test@example.com"
    PASS_DEFAULT  = "test1234"
    email    = st.text_input("Email", value=st.session_state.get("email", EMAIL_DEFAULT))
    password = st.text_input("Password", value=st.session_state.get("password", PASS_DEFAULT), type="password")

    if st.button("ログイン"):
        try:
            res = requests.post(_u("/login"), json={"email": email, "password": password}, timeout=10)
            res.raise_for_status()
            token = res.json().get("access_token")
            if not token:
                raise RuntimeError("access_token が空です")
            st.session_state["email"] = email
            st.session_state["password"] = password
            st.session_state["token"] = token
            st.success("ログイン成功")
        except Exception as e:
            st.error(f"Login failed: {e}")

token = st.session_state.get("token")
headers = {"Authorization": f"Bearer {token}"} if token else {}

st.divider()

# -----------------------------
# 実行パラメータ
# -----------------------------
col1, col2, col3, col4, col5 = st.columns([1,1,1,1,2])
with col1:
    mae_threshold = st.number_input("MAE threshold", value=0.008, format="%.6f")
with col2:
    min_new_labels = st.number_input("Min new labels（0=無効）", value=10, min_value=0, step=1)
with col3:
    top_k = st.number_input("Top-K features", value=3, min_value=1, step=1)
with col4:
    auto_promote = st.checkbox("Auto promote（本番のみ反映）", value=True)
with col5:
    note = st.text_input("Note", f"UI run {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def call_scheduler(dry_run: bool):
    if not token:
        st.warning("左のサイドバーでログインしてください。")
        return
    body = {
        "mae_threshold": float(mae_threshold),
        "min_new_labels": None if min_new_labels <= 0 else int(min_new_labels),
        "top_k": int(top_k),
        "auto_promote": (not dry_run) and bool(auto_promote),
        "note": note,
    }
    try:
        r = requests.post(_u("/scheduler/run"), headers=headers, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
        st.success("実行完了")

        st.subheader("結果（checked_models）")
        st.dataframe(data.get("checked_models", []), use_container_width=True)

        st.subheader("結果（triggered）")
        st.dataframe(data.get("triggered", []), use_container_width=True)

        promoted = [x for x in data.get("triggered", []) if x.get("promoted")]
        if promoted:
            st.success(f"昇格が {len(promoted)} 件ありました（SHAP自動再計算も実行済み）")
        else:
            st.info("今回の実行では昇格なし（SHAP自動再計算は未実行）")
    except Exception as e:
        st.error(f"Run failed: {e}")

c1, c2 = st.columns(2)
with c1:
    if st.button("▶︎ ドライラン（昇格なし）"):
        call_scheduler(dry_run=True)
with c2:
    if st.button("🚀 本番（条件成立で昇格）"):
        call_scheduler(dry_run=False)

st.divider()
st.subheader("履歴（/scheduler/status）")
if token:
    try:
        r = requests.get(_u("/scheduler/status"), headers=headers, timeout=15)
        r.raise_for_status()
        st.dataframe(r.json(), use_container_width=True)
    except Exception as e:
        st.error(f"Status failed: {e}")
else:
    st.info("ログインすると履歴が表示されます。")