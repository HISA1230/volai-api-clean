# login_ui.py
# -*- coding: utf-8 -*-
import os
import requests
import streamlit as st

def _api_base() -> str:
    """
    APIベースURLの決定（優先順）:
      1) streamlit_app.py が入れた session_state["API_BASE"]
      2) secrets.toml の API_BASE
      3) 環境変数 API_BASE
      4) 既定（本番API）
    """
    val = st.session_state.get("API_BASE")
    if val:
        return val.rstrip("/")

    try:
        if "API_BASE" in st.secrets and st.secrets["API_BASE"]:
            return str(st.secrets["API_BASE"]).rstrip("/")
    except Exception:
        pass

    env = os.environ.get("API_BASE")
    if env:
        return env.rstrip("/")

    # ← 既定は本番APIにしておく（ローカルAPI未起動でも困らない）
    return "https://volai-api-02.onrender.com"


def _set_token(token: str, email: str | None = None) -> None:
    """両方のキーに保存（互換性のため）"""
    st.session_state["access_token"] = token
    st.session_state["token"] = token
    if email:
        st.session_state["login_email"] = email


def _do_login(email: str, password: str) -> tuple[bool, str]:
    base = _api_base()
    try:
        resp = requests.post(
            f"{base}/login",
            json={"email": email, "password": password},
            timeout=20,
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            if not token:
                return False, "トークンが取得できませんでした"
            _set_token(token, email)
            return True, "ログイン成功"
        if resp.status_code in (401, 403):
            return False, "認証エラー：メール/パスワードをご確認ください。"
        return False, f"ログイン失敗: {resp.status_code} - {resp.text}"
    except Exception as e:
        return False, f"通信エラー: {e}"


def _do_logout() -> None:
    for k in ("access_token", "token", "login_email", "token_initialized"):
        st.session_state.pop(k, None)


def main():
    # サイドバー（≪/≫で畳める）
    with st.sidebar:
        st.markdown("### 接続情報")
        st.code(_api_base())

        if "access_token" not in st.session_state and "token" not in st.session_state:
            st.markdown("### ログイン")

            # secrets から既定値
            try:
                default_email = st.secrets.get("UI_EMAIL", "")
                default_pw    = st.secrets.get("UI_PASSWORD", "")
                auto_default  = bool(st.secrets.get("AUTO_LOGIN", False))
            except Exception:
                default_email, default_pw, auto_default = "", "", False

            email = st.text_input(
                "Email",
                value=st.session_state.get("login_email", default_email),
                key="login_email_input",
            )
            pw = st.text_input(
                "Password",
                type="password",
                value=default_pw,
                key="login_password_input",
            )
            auto = st.checkbox("起動時に自動ログイン", value=auto_default or bool(default_email and default_pw))

            # 起動時の自動ログイン（1回だけ）
            if auto and default_email and default_pw and not st.session_state.get("token_initialized"):
                ok, msg = _do_login(default_email, default_pw)
                if ok:
                    st.success("自動ログインしました。")
                else:
                    st.warning(f"自動ログイン失敗: {msg}")
                st.session_state["token_initialized"] = True

            if st.button("ログイン"):
                ok, msg = _do_login(email, pw)
                (st.success if ok else st.error)(msg)

            # 手動でトークン貼り付け
            with st.expander("🔑 トークンを手動設定（Swaggerで取得したものを貼り付け可）"):
                manual = st.text_input("Bearer Token", type="password", placeholder="eyJhbGciOi...")
                if st.button("Use this token"):
                    if manual:
                        _set_token(manual, email or None)
                        st.success("トークンを設定しました")
        else:
            who = st.session_state.get("login_email", "（不明）")
            st.success(f"ログイン中: {who}")
            if st.button("ログアウト"):
                _do_logout()
                st.info("ログアウトしました。")

    # メイン領域
    if st.session_state.get("access_token") or st.session_state.get("token"):
        st.header("ダッシュボード")
        st.write("左のサイドバーからページ（例：Scheduler）を選択してください。")
    else:
        st.info("サイドバーからログインしてください。")


# Streamlit エントリポイント
if __name__ == "__main__":
    main()