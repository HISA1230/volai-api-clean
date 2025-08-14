# streamlit_app.py
# -*- coding: utf-8 -*-
import os
import streamlit as st

def _detect_api_base() -> str:
    """
    APIベースURLの決定ロジック（優先順）:
      1) クエリパラメータ ?api=...
      2) Streamlit Secrets の API_BASE
      3) 環境変数 API_BASE
      4) ローカル既定 "http://127.0.0.1:8888"
    """
    # ① クエリパラメータ（新API）
    try:
        qp = st.query_params
        api_qp = qp.get("api", None)
        if api_qp:
            return api_qp if isinstance(api_qp, str) else api_qp[0]
    except Exception:
        # 旧API互換
        try:
            qp = st.experimental_get_query_params()
            api_qp = qp.get("api", None)
            if api_qp:
                return api_qp[0] if isinstance(api_qp, list) else str(api_qp)
        except Exception:
            pass

    # ② Secrets
    try:
        if "API_BASE" in st.secrets and st.secrets["API_BASE"]:
            return st.secrets["API_BASE"]
    except Exception:
        pass

    # ③ 環境変数
    api_env = os.environ.get("API_BASE")
    if api_env:
        return api_env

    # ④ 既定（ローカル）
    return "http://127.0.0.1:8888"


def main():
    # ← Streamlit の最初のコマンドとして1回だけ呼ぶ
    st.set_page_config(
        page_title="Volatility AI UI",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",  # ≪/≫ トグルを出す前提づくり
    )

    # サイドバーに何か1要素置くと ≪/≫ トグルが出る
    with st.sidebar:
        st.markdown(" ")  # 空でOK（タイトルでもOK）

    api_base = _detect_api_base()
    st.session_state["API_BASE"] = api_base     # 下流UIが参照
    os.environ["API_BASE"] = api_base           # 互換のため

    # ヘッダー
    st.title("高精度ボラ予測AI UI")
    st.caption("Ver.2030 構想：FastAPI + PostgreSQL + AutoML + SHAP（Streamlitフロント）")

    # 参照リンクと現在値
    st.info(f"API Base: `{api_base}`  ｜ Swagger: {api_base}/docs")

    # 既存の実アプリへ委譲（login_ui.py があれば）
    try:
        from login_ui import main as run_app
        run_app()  # 既存UIのエントリポイントに丸投げ
    except Exception as e:
        # フォールバック（login_uiが無い/壊れている場合に最低限の案内）
        st.error("`login_ui.py` の起動に失敗しました。下の例外を確認してください。")
        st.exception(e)
        st.write("プロジェクト内に `login_ui.py` もしくは `pages/` 配下のページを配置してください。")
        st.write("例： `pages/02_Scheduler.py` は自動でサイドバーに表示されます。")


if __name__ == "__main__":
    main()