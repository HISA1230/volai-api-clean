# login_ui.py
# -*- coding: utf-8 -*-
import os
import requests
import streamlit as st

def _api_base() -> str:
    # streamlit_app.py で入れている値を優先
    return st.session_state.get("API_BASE") or os.environ.get("API_BASE", "http://127.0.0.1:8888")

def _do_login(email: str, password: str):
    base = _api_base().rstrip("/")
    resp = requests.post(f"{base}/login", json={"email": email, "password": password}, timeout=10)
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in response")
    st.session_state["access_token"] = token
    st.session_state["login_email"] = email

def _do_logout():
    for k in ("access_token", "login_email", "token_initialized"):
        st.session_state.pop(k, None)

def main():
    # サイドバーにログイン欄（≪/≫で隠せる）
    with st.sidebar:
        st.markdown("### 接続情報")
        st.code(_api_base())

        if "access_token" not in st.session_state:
            st.markdown("### ログイン")
            # secrets から既定値
            try:
                default_email = st.secrets.get("UI_EMAIL", "")
                default_pw    = st.secrets.get("UI_PASSWORD", "")
            except Exception:
                default_email, default_pw = "", ""

            email = st.text_input("Email", value=st.session_state.get("login_email", default_email), key="login_email_input")
            pw    = st.text_input("Password", type="password", value=default_pw, key="login_password_input")
            auto  = st.checkbox("起動時に自動ログイン", value=bool(default_email and default_pw))

            # 起動時に一度だけ自動ログイン
            if auto and default_email and default_pw and not st.session_state.get("token_initialized"):
                try:
                    _do_login(default_email, default_pw)
                    st.session_state["token_initialized"] = True
                    st.success("自動ログインしました。")
                except Exception as e:
                    st.warning(f"自動ログイン失敗: {e}")

            if st.button("ログイン"):
                try:
                    _do_login(email, pw)
                    st.success("ログイン成功")
                except Exception as e:
                    st.error(f"ログイン失敗: {e}")
        else:
            st.success(f"ログイン中: {st.session_state.get('login_email','(不明)')}")
            if st.button("ログアウト"):
                _do_logout()
                st.info("ログアウトしました。")

    # メイン領域
    if "access_token" in st.session_state:
        st.header("ダッシュボード")
        st.write("左のサイドバーからページ（例：Scheduler）を選択してください。")
    else:
        st.info("サイドバーからログインしてください。")