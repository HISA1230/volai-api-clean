# streamlit_app.py
# -*- coding: utf-8 -*-
import os
import requests
import streamlit as st
import pandas as pd

def _detect_api_base() -> str:
    # 1) ?api=... 2) secrets 3) 環境変数 4) 既定(ローカル)
    try:
        qp = st.query_params
        api_qp = qp.get("api", None)
        if api_qp:
            return api_qp if isinstance(api_qp, str) else api_qp[0]
    except Exception:
        try:
            qp = st.experimental_get_query_params()
            api_qp = qp.get("api", None)
            if api_qp:
                return api_qp[0] if isinstance(api_qp, list) else str(api_qp)
        except Exception:
            pass
    try:
        if "API_BASE" in st.secrets and st.secrets["API_BASE"]:
            return st.secrets["API_BASE"]
    except Exception:
        pass
    api_env = os.environ.get("API_BASE")
    if api_env:
        return api_env
    return "https://volai-api-02.onrender.com"

def _secret(key: str, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)

def api_post(base, path, json=None, token=None, timeout=30):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.post(f"{base}{path}", json=json, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def api_get(base, path, token=None, params=None, timeout=30):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(f"{base}{path}", params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def main():
    st.set_page_config(page_title="Volatility AI UI", page_icon="📈", layout="wide")

    api_base = _detect_api_base()
    st.session_state.setdefault("API_BASE", api_base)
    st.session_state.setdefault("token", None)

    st.title("📈 高精度ボラ予測AI ダッシュボード")
    st.caption("FastAPI + PostgreSQL + AutoML（Streamlit UI）")
    st.info(f"API Base: `{api_base}` ｜ Swagger: {api_base}/docs")

    with st.sidebar:
        st.subheader("🔐 ログイン")
        email_default = _secret("UI_EMAIL", "test@example.com")
        pwd_default   = _secret("UI_PASSWORD", "test1234")
        email = st.text_input("Email", email_default)
        pwd   = st.text_input("Password", pwd_default, type="password")
        col1, col2 = st.columns(2)
        if col1.button("Login", use_container_width=True):
            try:
                resp = api_post(api_base, "/login", {"email": email, "password": pwd})
                st.session_state["token"] = resp["access_token"]
                st.success("ログイン成功")
            except Exception as e:
                st.session_state["token"] = None
                st.error(f"ログイン失敗: {e}")
        if col2.button("Logout", use_container_width=True):
            st.session_state["token"] = None
            st.info("ログアウトしました")

    # 自動ログイン（secretsのAUTO_LOGINがtrueなら）
    auto = _secret("AUTO_LOGIN", "true")
    auto = str(auto).lower() in ("1", "true", "yes", "on")
    if auto and not st.session_state["token"]:
        try:
            resp = api_post(api_base, "/login", {
                "email": _secret("UI_EMAIL", "test@example.com"),
                "password": _secret("UI_PASSWORD", "test1234"),
            })
            st.session_state["token"] = resp["access_token"]
            st.toast("自動ログインしました", icon="✅")
        except Exception:
            pass

    token = st.session_state["token"]
    if not token:
        st.warning("左のサイドバーからログインしてください。")
        st.stop()

    # /me で確認
    try:
        me = api_get(api_base, "/me", token=token)
        st.success(f"ログイン中: {me.get('email')}")
    except Exception as e:
        st.error(f"/me 失敗: {e}")
        st.stop()

    # サンプル表（あとでAPI連携に差し替え）
    st.markdown("### 📊 予測テーブル（サンプル）")
    sample = [
        {"日付":"2025-07-30","時間帯":"9:30–10:30","セクター":"Tech","サイズ":"Small","予測ボラ":0.036,"だまし率":0.18,"信頼度":"高","コメント":"CPI発表あり"},
        {"日付":"2025-07-30","時間帯":"12:00–13:30","セクター":"Utilities","サイズ":"Large","予測ボラ":0.008,"だまし率":0.42,"信頼度":"注意","コメント":"静穏"},
        {"日付":"2025-07-30","時間帯":"15:00–16:00","セクター":"Energy","サイズ":"Mid","予測ボラ":0.022,"だまし率":0.65,"信頼度":"低","コメント":"要注意"},
    ]
    st.dataframe(pd.DataFrame(sample), use_container_width=True)

if __name__ == "__main__":
    main()