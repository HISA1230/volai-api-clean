# pages/02_Scheduler.py
# -*- coding: utf-8 -*-
import os
from datetime import datetime
import requests
import streamlit as st
import pandas as pd

st.title("⏱️ スケジューラ（ドライラン / 本番）")

# ===== API Base 自動解決（?api > secrets > session > env > 既定=Render） =====
def _get_qp_api():
    try:
        qp = st.query_params
        v = qp.get("api")
        return v if isinstance(v, str) else (v[0] if v else None)
    except Exception:
        pass
    try:
        qp = st.experimental_get_query_params()
        v = qp.get("api")
        return v[0] if isinstance(v, list) and v else (str(v) if v else None)
    except Exception:
        return None

def _set_qp_api(val: str):
    try:
        st.query_params["api"] = val
        return
    except Exception:
        pass
    try:
        st.experimental_set_query_params(api=val)
    except Exception:
        pass

def _resolve_api_base_with_reason():
    v = _get_qp_api()
    if v: return v.rstrip("/"), "query_param"
    try:
        if "API_BASE" in st.secrets and st.secrets["API_BASE"]:
            return str(st.secrets["API_BASE"]).rstrip("/"), "secrets"
    except Exception:
        pass
    v = st.session_state.get("API_BASE")
    if v: return str(v).rstrip("/"), "session_state"
    v = os.environ.get("API_BASE")
    if v: return str(v).rstrip("/"), "env"
    return "https://volai-api-02.onrender.com", "default"

API_BASE, _src = _resolve_api_base_with_reason()
st.session_state["API_BASE"] = API_BASE
st.session_state["API_BASE_SRC"] = _src
_set_qp_api(API_BASE)

def _u(path: str) -> str:
    return f"{API_BASE}{path}"

def _auth_headers() -> dict:
    tok = st.session_state.get("access_token") or st.session_state.get("token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

st.info(f"API Base: `{API_BASE}` | Source: **{_src}** | Swagger: {API_BASE}/docs")

# ===== サイドバー：接続＆ログイン（手動変更UIは撤去） =====
with st.sidebar:
    st.subheader("接続設定（自動）")
    # /health で疎通確認
    ok, msg = False, ""
    try:
        r = requests.get(_u("/health"), timeout=6)
        ok = r.ok
        msg = (r.text or "")[:160]
    except Exception as e:
        msg = f"ping error: {e}"
    st.write("API疎通:", "🟢 OK" if ok else "🔴 NG")
    st.caption(msg)

    st.subheader("ログイン")
    try:
        EMAIL_DEFAULT = st.secrets.get("UI_EMAIL", "test@example.com")
        PASS_DEFAULT  = st.secrets.get("UI_PASSWORD", "test1234")
    except Exception:
        EMAIL_DEFAULT, PASS_DEFAULT = "test@example.com", "test1234"

    email = st.text_input("Email", value=st.session_state.get("login_email", EMAIL_DEFAULT))
    password = st.text_input("Password", value=PASS_DEFAULT, type="password")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("ログイン", use_container_width=True):
            try:
                res = requests.post(_u("/login"), json={"email": email, "password": password}, timeout=10)
                res.raise_for_status()
                token = res.json().get("access_token")
                if not token:
                    raise RuntimeError("access_token が空です")
                st.session_state["login_email"] = email
                st.session_state["access_token"] = token
                st.session_state["token"] = token
                st.success("ログイン成功")
            except Exception as e:
                st.error(f"Login failed: {e}")
    with c2:
        if st.button("ログアウト", use_container_width=True):
            for k in ("access_token", "token", "login_email"):
                st.session_state.pop(k, None)
            st.info("ログアウトしました。")

token_exists = bool(st.session_state.get("access_token") or st.session_state.get("token"))
headers = _auth_headers()

st.divider()

# ===== 実行パラメータ =====
c1, c2, c3, c4, c5 = st.columns([1,1,1,1,2])
with c1: mae_threshold = st.number_input("MAE threshold", value=0.008, format="%.6f")
with c2: min_new_labels = st.number_input("Min new labels（0=無効）", value=10, min_value=0, step=1)
with c3: top_k = st.number_input("Top-K features", value=3, min_value=1, step=1)
with c4: auto_promote = st.checkbox("Auto promote（本番のみ反映）", value=True)
with c5: note = st.text_input("Note", f"UI run {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def call_scheduler(dry_run: bool):
    if not token_exists:
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
        if r.status_code == 404:
            st.error("`/scheduler/run` が見つかりません。サーバ側で scheduler_router を有効化してください。")
            return
        r.raise_for_status()
        data = r.json()
        st.success("実行完了")

        if isinstance(data, dict):
            if "checked_models" in data:
                st.subheader("結果（checked_models）")
                st.dataframe(pd.DataFrame(data.get("checked_models") or []), use_container_width=True)
            if "triggered" in data:
                st.subheader("結果（triggered）")
                df_tr = pd.DataFrame(data.get("triggered") or [])
                st.dataframe(df_tr, use_container_width=True)
                if not df_tr.empty and "promoted" in df_tr.columns:
                    cnt = int(df_tr["promoted"].fillna(False).sum())
                    st.success(f"昇格 {cnt} 件")
        else:
            st.write(data)
    except Exception as e:
        st.error(f"Run failed: {e}")

colA, colB = st.columns(2)
with colA:
    if st.button("▶ ドライラン（昇格なし）", use_container_width=True):
        call_scheduler(dry_run=True)
with colB:
    if st.button("🚀 本番（条件成立で昇格）", use_container_width=True):
        call_scheduler(dry_run=False)

st.divider()
st.subheader("履歴（/scheduler/status）")
if token_exists:
    try:
        r = requests.get(_u("/scheduler/status"), headers=headers, timeout=15)
        if r.status_code == 404:
            st.error("`/scheduler/status` が見つかりません。サーバ側で scheduler_router を有効化してください。")
        else:
            r.raise_for_status()
            val = r.json()
            if isinstance(val, dict) and "value" in val:
                val = val["value"]
            df = pd.DataFrame(val if isinstance(val, list) else [])
            if df.empty:
                st.info("履歴はありません。")
            else:
                st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.error(f"Status failed: {e}")
else:
    st.info("ログインすると履歴が表示されます。")