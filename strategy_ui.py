# strategy_ui.py（SHAP可視化＋再計算＋モデルアーカイブ＋メタ編集＋スケジューラ：API_BASE自動解決版）
# -*- coding: utf-8 -*-
import os
import joblib
import requests
import pandas as pd
import altair as alt
import shap
import matplotlib.pyplot as plt
import streamlit as st

# =========================
# 共通ユーティリティ
# =========================
def resolve_api_base() -> str:
    """
    API Base を 1) ?api=… 2) secrets 3) session_state 4) 環境変数 5) 既定 の優先順で決定
    """
    # 1) Query parameter
    try:
        qp = st.query_params
        api_qp = qp.get("api", None)
        if api_qp:
            return api_qp if isinstance(api_qp, str) else api_qp[0]
    except Exception:
        # 旧API
        try:
            qp = st.experimental_get_query_params()
            api_qp = qp.get("api", None)
            if api_qp:
                return api_qp[0] if isinstance(api_qp, list) else str(api_qp)
        except Exception:
            pass

    # 2) secrets.toml
    try:
        if "API_BASE" in st.secrets and st.secrets["API_BASE"]:
            return st.secrets["API_BASE"]
    except Exception:
        pass

    # 3) session_state（他ページや親UIから引き継ぎ）
    if st.session_state.get("API_BASE"):
        return st.session_state["API_BASE"]

    # 4) 環境変数
    api_env = os.environ.get("API_BASE")
    if api_env:
        return api_env

    # 5) 既定（本番APIに倒す）
    return "https://volai-api-02.onrender.com"


def get_token() -> str | None:
    """token or access_token を許容（どちらでも使えるように）"""
    return st.session_state.get("token") or st.session_state.get("access_token")


def auth_headers() -> dict:
    tok = get_token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def api_get(base: str, path: str, **kw):
    return requests.get(f"{base}{path}", **kw)


def api_post(base: str, path: str, **kw):
    return requests.post(f"{base}{path}", **kw)


def api_delete(base: str, path: str, **kw):
    return requests.delete(f"{base}{path}", **kw)


# =========================
# 基本設定
# =========================
st.set_page_config(layout="wide")
st.title("📈 高精度ボラ予測AIアプリ Ver.2030")

API_BASE = resolve_api_base()
st.session_state["API_BASE"] = API_BASE  # 他ページでも参照できるよう共有

st.info(f"API Base: `{API_BASE}` ｜ Swagger: {API_BASE}/docs")

# =========================
# 🔐 サイドバー：簡易ログイン
# =========================
st.sidebar.subheader("🔐 ログイン")
# secrets があれば初期値に利用（任意）
try:
    _def_email = st.secrets.get("UI_EMAIL", "test@example.com")
    _def_pw = st.secrets.get("UI_PASSWORD", "test1234")
except Exception:
    _def_email, _def_pw = "test@example.com", "test1234"

email = st.sidebar.text_input("Email", value=st.session_state.get("login_email", _def_email))
password = st.sidebar.text_input("Password", type="password", value=_def_pw)

col_login1, col_login2 = st.sidebar.columns(2)
with col_login1:
    if st.button("Sign in", use_container_width=True):
        try:
            res = api_post(API_BASE, "/login", json={"email": email, "password": password}, timeout=20)
            if res.status_code == 200:
                token = res.json().get("access_token")
                if token:
                    st.session_state["token"] = token
                    st.session_state["access_token"] = token
                    st.session_state["login_email"] = email
                    st.sidebar.success("ログイン成功！")
                else:
                    st.sidebar.error("トークンが取得できませんでした")
            elif res.status_code in (401, 403):
                st.sidebar.error("認証エラー：メール/パスワードをご確認ください。")
            else:
                st.sidebar.error(f"ログイン失敗: {res.status_code} - {res.text}")
        except Exception as e:
            st.sidebar.error(f"通信エラー: {e}")

with col_login2:
    if st.button("ログアウト", use_container_width=True):
        for k in ("token", "access_token", "login_email"):
            st.session_state.pop(k, None)
        st.sidebar.info("ログアウトしました。")

with st.sidebar.expander("🔑 トークンを手動設定（Swaggerで取得したものを貼り付け可）"):
    manual_token = st.text_input("Bearer Token", type="password", placeholder="eyJhbGciOi...")
    if st.button("Use this token", use_container_width=True):
        if manual_token:
            st.session_state["token"] = manual_token
            st.session_state["access_token"] = manual_token
            st.sidebar.success("トークン設定しました")

# =========================
# 🔍 モデル選択（APIから取得・既定モデルを初期選択）
# =========================
st.subheader("🔍 モデル選択（SHAP解析）")

def fetch_models():
    try:
        r = api_get(API_BASE, "/models", headers=auth_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            st.warning("認証が必要です。左の『ログイン』からサインインしてください。")
        else:
            st.error(f"モデル取得エラー: {r.status_code} - {r.text}")
    except Exception as e:
        st.error(f"通信エラー: {e}")
    return {"default_model": "", "models": []}

def fetch_default_model():
    try:
        r = api_get(API_BASE, "/models/default", headers=auth_headers(), timeout=10)
        if r.status_code == 200:
            return r.json().get("default_model")
    except Exception:
        pass
    return ""

models_payload = fetch_models()
models_list = models_payload.get("models", [])
api_default_model = models_payload.get("default_model") or fetch_default_model()

if models_list:
    option_labels = [m.get("name") or os.path.basename(m.get("path", "")) for m in models_list]
    option_values = [m["path"] for m in models_list]
else:
    option_labels = ["Standard Model", "Top SHAP Features Model"]
    option_values = ["models/vol_model.pkl", "models/vol_model_top_features.pkl"]

init_index = 0
if api_default_model and api_default_model in option_values:
    init_index = option_values.index(api_default_model)

selected_label = st.selectbox("使用するモデル:", option_labels, index=init_index if option_labels else 0)
selected_model_path = option_values[option_labels.index(selected_label)] if option_labels else "models/vol_model.pkl"

st.caption(f"選択中のモデル: `{selected_model_path}`")
st.divider()

# =========================
# 📊 SHAP 特徴量重要度の表示（詳細プロット：SHAP/Matplotlib）
# =========================
st.subheader("📊 SHAP 特徴量重要度の表示（詳細プロット）")
st.caption("※ モデル別の *_shap_values.pkl が無い場合は、下の『SHAPを再計算して保存』で生成してください。")

def guess_shap_values_paths(model_path: str):
    base = os.path.splitext(model_path)[0]
    return [
        f"{base}_shap_values.pkl",  # 推奨：モデル別
        "shap_values.pkl",          # 互換：単一ファイル
    ]

if st.button("🌀 SHAP特徴量重要度を表示", use_container_width=True):
    shap_values = None
    chosen_path = None
    for p in guess_shap_values_paths(selected_model_path):
        if os.path.exists(p):
            try:
                shap_values = joblib.load(p)
                chosen_path = p
                break
            except Exception:
                pass

    if shap_values is None:
        st.error("❌ shap_values.pkl が見つかりません。下の『SHAPを再計算して保存』を押して生成してください。")
    else:
        st.caption(f"データソース: `{chosen_path}`")
        try:
            st.write("🔝 平均SHAPバー（上位10）")
            fig, _ = plt.subplots(figsize=(10, 6))
            shap.plots.bar(shap_values, max_display=10, show=False)
            st.pyplot(fig)

            st.write("🧩 サマリープロット")
            fig2 = plt.figure()
            shap.summary_plot(shap_values, show=False)
            st.pyplot(fig2)
        except Exception as e:
            st.error(f"SHAP描画エラー: {e}")

st.divider()

# =========================
# 🔁 SHAP 再計算（FastAPIにPOST）
# =========================
st.subheader("🔁 SHAP 再計算（再学習なし）")
st.caption("選択中のモデルで、DBの実測付きデータからSHAP値を再計算して保存します。")

recompute_sample = st.slider("SHAP再計算に使うサンプル件数（上限）", 128, 4096, 512, step=128)

c1, c2 = st.columns(2)
with c1:
    st.write(f"モデル: `{selected_model_path}`")
with c2:
    st.write(f"サンプル上限: `{recompute_sample}` 件")

if st.button("📊 SHAPを再計算して保存", use_container_width=True):
    try:
        payload = {
            "model_path": selected_model_path,
            "sample_size": int(recompute_sample),
            "feature_cols": ["rci", "atr", "vix"],  # 必要に応じて差し替え
        }
        res = api_post(API_BASE, "/predict/shap/recompute",
                       json=payload, headers=auth_headers(), timeout=60)
        if res.status_code == 200:
            data = res.json()
            st.success(f"✅ {data.get('message','完了')}")
            st.write(f"- shap_values: `{data.get('shap_values_path','')}`")
            st.write(f"- summary_csv: `{data.get('summary_csv_path','')}`")
            if data.get("top_features"):
                st.write(f"- 上位特徴量: {data['top_features']}")
        elif res.status_code == 401:
            st.error("❌ 認証が必要です。左の『ログイン』からサインインしてから再実行してください。")
        else:
            st.error(f"❌ エラー: {res.status_code} - {res.text}")
    except Exception as e:
        st.error(f"通信エラー: {e}")

st.info("⚠️ 注意：FastAPI の `/predict/shap/recompute` は認証が必要です。401 の場合はログインしてトークンを取得してください。")

# =========================
# ⚡ 高速SHAPバー（Altair）
# =========================
st.subheader("⚡ SHAP 重要度バー（高速表示）")

def summary_paths_for_model(model_path: str):
    base = os.path.splitext(model_path)[0]
    return [
        f"{base}_shap_summary.csv",  # 推奨：モデル別
        "models/shap_summary.csv",   # 互換：単一ファイル
    ]

top_k = st.slider("表示する上位特徴量の数", 3, 20, 10, step=1)

summary_df = None
source_path = None
for p in summary_paths_for_model(selected_model_path):
    if os.path.exists(p):
        try:
            df_tmp = pd.read_csv(p)
            if {"feature", "mean_abs_shap"}.issubset(df_tmp.columns):
                summary_df = df_tmp.copy()
                source_path = p
                break
        except Exception:
            pass

if summary_df is None:
    st.warning("shap_summary.csv が見つかりません。まず『📊 SHAPを再計算して保存』で生成してください。")
else:
    summary_df = summary_df[["feature", "mean_abs_shap"]].dropna()
    summary_df = summary_df.sort_values("mean_abs_shap", ascending=False).head(top_k)

    st.caption(f"データソース: `{source_path}`")
    chart = (
        alt.Chart(summary_df)
        .mark_bar()
        .encode(
            x=alt.X("mean_abs_shap:Q", title="平均 |SHAP|"),
            y=alt.Y("feature:N", sort="-x", title="特徴量"),
            tooltip=[
                alt.Tooltip("feature:N", title="特徴量"),
                alt.Tooltip("mean_abs_shap:Q", title="平均 |SHAP|", format=".5f"),
            ],
        )
        .properties(height=max(180, 30 * len(summary_df)), width=600)
    )
    st.altair_chart(chart, use_container_width=True)

    with st.expander("表で確認する"):
        st.dataframe(summary_df.reset_index(drop=True), use_container_width=True)

st.divider()

# =========================
# 📦 モデルアーカイブ（一覧／既定設定／リネーム／削除）
# =========================
st.header("📦 モデルアーカイブ")

with st.expander("🔎 検索・フィルタ"):
    q = st.text_input("フリーテキスト検索（名前/説明/タグに対して）", value="")
    selected_tag = st.text_input("タグで絞り込み（完全一致・例: prod）", value="")

def fetch_models_safe(query: str = "", tag: str = ""):
    try:
        params = {}
        if query:
            params["q"] = query
        if tag:
            params["tag"] = tag

        r = api_get(API_BASE, "/models", params=params, headers=auth_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            st.warning("認証が必要です。左の『ログイン』からサインインしてください。")
        else:
            st.error(f"取得エラー: {r.status_code} - {r.text}")
    except Exception as e:
        st.error(f"通信エラー: {e}")
    return {"default_model": "", "models": []}

colA, colB = st.columns([2, 1])
with colA:
    st.subheader("📃 モデル一覧")
with colB:
    if st.button("🔄 再読み込み", use_container_width=True):
        st.rerun()

models_payload = fetch_models_safe(q, selected_tag)
default_model = models_payload.get("default_model", "")
models_list = models_payload.get("models", [])

if not models_list:
    st.info("models/ に *.pkl が見つかりません。再学習やファイル配置を行ってください。")
else:
    df = pd.DataFrame(models_list)

    if "mae" in df.columns:
        df["MAE"] = df["mae"].apply(lambda x: f"{x:.4f}" if pd.notnull(x) else "—")
    if "size_bytes" in df.columns:
        df["サイズ(KB)"] = (df["size_bytes"] / 1024).round(1)
    if "updated_at" in df.columns:
        df["最終更新"] = pd.to_datetime(df["updated_at"]).dt.strftime("%m/%d %H:%M")
    if "tags" in df.columns:
        df["タグ"] = df["tags"].apply(lambda xs: ", ".join(xs) if isinstance(xs, list) else "")
    if "description" in df.columns:
        df["メモ"] = df["description"].fillna("")

    show_cols = ["name", "サイズ(KB)", "最終更新", "MAE", "タグ", "メモ", "path"]
    show_cols = [c for c in show_cols if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    names = [m["name"] for m in models_list]
    idx_default = 0
    if default_model:
        base = os.path.basename(default_model)
        if base in names:
            idx_default = names.index(base)

    selected_name = st.selectbox("操作するモデル", names, index=idx_default if len(names) > 0 else 0)
    selected_path = f"models/{selected_name}"

    st.caption(f"既定モデル: `{default_model or '（未設定）'}`")

    c1, c2, c3 = st.columns([1, 1, 2])

    # 既定に設定
    with c1:
        if st.button("⭐ 既定に設定", use_container_width=True):
            try:
                r = api_post(API_BASE, "/models/default",
                             json={"model_path": selected_path},
                             headers=auth_headers(), timeout=15)
                if r.status_code == 200:
                    st.success("既定モデルを更新しました。")
                    st.rerun()
                elif r.status_code == 401:
                    st.error("認証が必要です。左の『ログイン』からサインインしてください。")
                else:
                    st.error(f"エラー: {r.status_code} - {r.text}")
            except Exception as e:
                st.error(f"通信エラー: {e}")

    # リネーム
    with c2:
        new_name = st.text_input("新しいファイル名（.pkl）", value=selected_name.replace(".pkl", "_v2.pkl"))
        if st.button("✏️ リネーム", use_container_width=True):
            if new_name.strip():
                try:
                    r = api_post(API_BASE, "/models/rename",
                                 json={"old_name": selected_name, "new_name": new_name},
                                 headers=auth_headers(), timeout=15)
                    if r.status_code == 200:
                        st.success("リネームしました。付随する SHAP ファイルも可能な範囲で改名しています。")
                        st.rerun()
                    elif r.status_code == 401:
                        st.error("認証が必要です。左の『ログイン』からサインインしてください。")
                    else:
                        st.error(f"エラー: {r.status_code} - {r.text}")
                except Exception as e:
                    st.error(f"通信エラー: {e}")
            else:
                st.warning("新しいファイル名を入力してください。")

    # 削除
    with c3:
        colx, coly = st.columns([1, 2])
        with colx:
            confirm = st.checkbox("削除の確認", value=False)
        with coly:
            if st.button("🗑️ 削除", use_container_width=True) and confirm:
                try:
                    r = api_delete(API_BASE, "/models",
                                   json={"model_path": selected_path},
                                   headers=auth_headers(), timeout=15)
                    if r.status_code == 200:
                        st.success("モデルを削除しました。")
                        st.rerun()
                    elif r.status_code == 400:
                        st.error("既定モデルは削除できません。先に既定を別モデルに変更してください。")
                    elif r.status_code == 401:
                        st.error("認証が必要です。左の『ログイン』からサインインしてください。")
                    else:
                        st.error(f"エラー: {r.status_code} - {r.text}")
                except Exception as e:
                    st.error(f"通信エラー: {e}")

st.divider()

# =========================
# 📝 モデルのメタ情報 編集UI
# =========================
st.header("📝 モデルのメタ情報 編集")

def _fetch_models_for_meta():
    try:
        r = api_get(API_BASE, "/models", headers=auth_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            st.warning("認証が必要です。左の『ログイン』からサインインしてください。")
        else:
            st.error(f"取得エラー: {r.status_code} - {r.text}")
    except Exception as e:
        st.error(f"通信エラー: {e}")
    return {"default_model": "", "models": []}

payload_meta = _fetch_models_for_meta()
models_meta_list = payload_meta.get("models", [])
if not models_meta_list:
    st.info("モデルが見つかりません。まずはモデルを作成/再学習してください。")
else:
    names_meta = [m["name"] for m in models_meta_list]
    sel_name_meta = st.selectbox("メタ情報を編集するモデル", names_meta, key="meta_select_model")
    sel_path_meta = f"models/{sel_name_meta}"

    # 現在のメタ取得
    try:
        r = api_get(API_BASE, "/models/meta",
                    params={"model_path": sel_path_meta},
                    headers=auth_headers(), timeout=15)
        meta = r.json().get("meta", {}) if r.status_code == 200 else {}
    except Exception:
        meta = {}

    colL, colR = st.columns([2, 3])
    with colL:
        display_name = st.text_input("表示名（display_name）", value=meta.get("display_name", ""))
        version = st.text_input("バージョン（version）", value=meta.get("version", ""))
        owner = st.text_input("オーナー（owner）", value=meta.get("owner", ""))
        pinned = st.checkbox("📌 ピン留め（一覧の上位に表示）", value=meta.get("pinned", False))
    with colR:
        description = st.text_area("説明（description）", value=meta.get("description", ""), height=120)
        tags_str = st.text_input("タグ（カンマ区切り可）", value=",".join(meta.get("tags", [])))

    csave, cpreview = st.columns([1, 1])

    with csave:
        if st.button("💾 メタ情報を保存", use_container_width=True):
            try:
                body = {
                    "model_path": sel_path_meta,
                    "display_name": display_name,
                    "version": version,
                    "owner": owner,
                    "description": description,
                    "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
                    "pinned": pinned,
                }
                r = api_post(API_BASE, "/models/meta",
                             json=body, headers=auth_headers(), timeout=15)
                if r.status_code == 200:
                    st.success("✅ 保存しました。")
                    st.rerun()
                elif r.status_code == 401:
                    st.error("認証が必要です。左の『ログイン』からサインインしてください。")
                else:
                    st.error(f"エラー: {r.status_code} - {r.text}")
            except Exception as e:
                st.error(f"通信エラー: {e}")

    with cpreview:
        if st.button("👀 現在のメタをプレビュー", use_container_width=True):
            st.write({
                "display_name": display_name,
                "version": version,
                "owner": owner,
                "description": description,
                "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
                "pinned": pinned,
            })

    with st.expander("現在保存されているメタ情報（読み取り）"):
        st.json(meta)

# =========================
# 🔬 モデル比較モード（MAE & SHAPサイドバイサイド）
# =========================
st.divider()
st.header("🔬 モデル比較モード")

def _fetch_models_list():
    try:
        r = api_get(API_BASE, "/models", headers=auth_headers(), timeout=15)
        if r.status_code == 200:
            payload = r.json()
            return payload.get("models", []), payload.get("default_model", "")
    except Exception:
        pass
    return [], ""

models_list2, default_model_path = _fetch_models_list()
if not models_list2:
    st.info("モデル一覧を取得できませんでした（未ログイン or モデル未登録）。左のログイン後、モデルを作成/再学習してください。")
else:
    names = [m["name"] for m in models_list2]
    paths = [m["path"] for m in models_list2]
    name_to_path = {n: p for n, p in zip(names, paths)}

    colA, colB = st.columns(2)
    with colA:
        selA = st.selectbox("Model A", names, index=0 if names else 0, key="cmpA")
    with colB:
        idx_default = names.index(os.path.basename(default_model_path)) if default_model_path and os.path.basename(default_model_path) in names else (1 if len(names) > 1 else 0)
        selB = st.selectbox("Model B", names, index=idx_default, key="cmpB")

    pathA = name_to_path.get(selA)
    pathB = name_to_path.get(selB)

    # --- MAE比較（prediction_logsから）
    st.subheader("📈 精度比較（MAE）")
    try:
        r = api_get(API_BASE, "/predict/logs", headers=auth_headers(), timeout=20)
        if r.status_code == 200:
            logs = r.json()
            if not logs:
                st.warning("予測ログがありません。/predict を実行してから比較してください。")
            else:
                df_logs = pd.DataFrame(logs)
                df_logs = df_logs[df_logs.get("abs_error").notnull()] if "abs_error" in df_logs.columns else pd.DataFrame()
                if df_logs.empty:
                    st.info("誤差（abs_error）がまだありません。/predict/actual で正解ラベルを登録してください。")
                else:
                    g = df_logs.groupby("model_path").agg(
                        MAE=("abs_error", "mean"),
                        N=("abs_error", "count")
                    ).reset_index()

                    def _pick(gdf, p):
                        try:
                            r_ = gdf[gdf["model_path"] == p]
                            return (float(r_["MAE"].values[0]), int(r_["N"].values[0]))
                        except Exception:
                            return (None, 0)

                    maeA, nA = _pick(g, pathA)
                    maeB, nB = _pick(g, pathB)

                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric(f"{selA}（N={nA}）", f"{maeA:.4f}" if maeA is not None else "—")
                    with c2:
                        st.metric(f"{selB}（N={nB}）", f"{maeB:.4f}" if maeB is not None else "—")

                    show = [
                        {"model": selA, "path": pathA, "MAE": f"{maeA:.4f}" if maeA is not None else "—", "N": nA},
                        {"model": selB, "path": pathB, "MAE": f"{maeB:.4f}" if maeB is not None else "—", "N": nB},
                    ]
                    st.dataframe(pd.DataFrame(show), use_container_width=True, hide_index=True)
        elif r.status_code == 401:
            st.error("認証が必要です。左の『ログイン』からサインインしてください。")
        else:
            st.error(f"ログ取得エラー: {r.status_code} - {r.text}")
    except Exception as e:
        st.error(f"通信エラー: {e}")

    # --- SHAP比較（summary CSVを横並び表示）
    st.subheader("🧠 SHAP 重要度比較（サイドバイサイド）")

    def _summary_for(path: str) -> pd.DataFrame | None:
        if not path:
            return None
        base = os.path.splitext(path)[0]
        candidates = [f"{base}_shap_summary.csv", "models/shap_summary.csv"]
        for cp in candidates:
            if os.path.exists(cp):
                try:
                    df = pd.read_csv(cp)
                    if {"feature", "mean_abs_shap"}.issubset(df.columns):
                        out = df[["feature", "mean_abs_shap"]].copy()
                        out["__source__"] = os.path.basename(path)
                        out["__title__"] = os.path.basename(path)
                        return out
                except Exception:
                    pass
        return None

    dfA = _summary_for(pathA)
    dfB = _summary_for(pathB)

    if (dfA is None) or (dfB is None):
        st.warning("どちらかのモデルの SHAPサマリCSV が見つかりません。『📊 SHAPを再計算して保存』を実行してください。")
    else:
        topK = st.slider("表示する上位特徴量の数（各モデル）", 3, 20, 10, step=1, key="cmp_topk")
        dfA_show = dfA.sort_values("mean_abs_shap", ascending=False).head(topK)
        dfB_show = dfB.sort_values("mean_abs_shap", ascending=False).head(topK)

        chartA = (
            alt.Chart(dfA_show)
            .mark_bar()
            .encode(
                x=alt.X("mean_abs_shap:Q", title=f"{selA} 平均|SHAP|"),
                y=alt.Y("feature:N", sort="-x", title="特徴量"),
                tooltip=[alt.Tooltip("feature:N"), alt.Tooltip("mean_abs_shap:Q", format=".5f")],
            )
            .properties(width=500, height=max(200, 30 * len(dfA_show)))
        )

        chartB = (
            alt.Chart(dfB_show)
            .mark_bar()
            .encode(
                x=alt.X("mean_abs_shap:Q", title=f"{selB} 平均|SHAP|"),
                y=alt.Y("feature:N", sort="-x", title="特徴量"),
                tooltip=[alt.Tooltip("feature:N"), alt.Tooltip("mean_abs_shap:Q", format=".5f")],
            )
            .properties(width=500, height=max(200, 30 * len(dfB_show)))
        )

        st.altair_chart(alt.hconcat(chartA, chartB), use_container_width=True)

        with st.expander("表で比較（A/B）"):
            left = dfA_show.rename(columns={"mean_abs_shap": f"{selA}_|SHAP|"})
            right = dfB_show.rename(columns={"mean_abs_shap": f"{selB}_|SHAP|"})
            merged = pd.merge(left, right, on="feature", how="outer")
            st.dataframe(merged.fillna("—"), use_container_width=True)

st.divider()

# =========================
# 📆 スケジューラ & SHAP（API連携）
# =========================
st.subheader("📆 スケジューラ & SHAP")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 既定モデルを取得", use_container_width=True):
        r = api_get(API_BASE, "/models/default", headers=auth_headers(), timeout=10)
        if r.ok:
            default_p = r.json().get("default_model", "")
            st.session_state["default_model"] = default_p
            st.success(default_p or "not set")
        elif r.status_code == 401:
            st.error("認証が必要です。左の『ログイン』からサインインしてください。")
        else:
            st.error(r.text)

with col2:
    mp = st.session_state.get("default_model")
    st.caption(f"SHAP再計算対象: {mp or '(未取得)'}")
    if st.button("♻️ SHAP再計算", use_container_width=True):
        if not mp:
            st.warning("先に既定モデルを取得してください。")
        else:
            r = api_post(
                API_BASE, "/predict/shap/recompute",
                headers={**auth_headers(), "Content-Type": "application/json"},
                json={"model_path": mp}, timeout=60
            )
            st.write(r.json() if r.ok else r.text)

with st.form("scheduler_run"):
    st.write("🧪 条件付き評価・再学習・昇格（A-30 実行）")
    mae = st.number_input("MAEしきい値", value=0.008, step=0.001, format="%.3f")
    mnl = st.number_input("最小ラベル数（昇格の下限）", min_value=0, value=10, step=1)
    topk = st.number_input("Top-K", min_value=1, value=3, step=1)
    ap = st.checkbox("自動昇格を有効化", value=True)
    note = st.text_input("メモ", value="manual run")
    run = st.form_submit_button("▶ 実行")
    if run:
        r = api_post(
            API_BASE, "/scheduler/run",
            headers={**auth_headers(), "Content-Type": "application/json"},
            json={
                "mae_threshold": float(mae),
                "min_new_labels": int(mnl),
                "top_k": int(topk),
                "auto_promote": bool(ap),
                "note": note
            },
            timeout=60
        )
        st.write(r.json() if r.ok else r.text)

if st.button("📜 履歴を更新", use_container_width=True):
    r = api_get(API_BASE, "/scheduler/status", headers=auth_headers(), timeout=15)
    if r.ok:
        val = r.json().get("value", [])
        df = pd.DataFrame(val)
        st.dataframe(df if not df.empty else pd.DataFrame([{"message": "no history"}]), use_container_width=True)
    elif r.status_code == 401:
        st.error("認証が必要です。左の『ログイン』からサインインしてください。")
    else:
        st.error(r.text)

# SHAPサマリ軽表示（既定モデル名から推定）
mp = st.session_state.get("default_model")
if mp:
    csv_guess = os.path.join("models", os.path.basename(mp).replace(".pkl", "_shap_summary.csv"))
    if os.path.exists(csv_guess):
        st.caption(f"SHAP summary: {csv_guess}")
        df = pd.read_csv(csv_guess)
        if {"feature", "mean_abs_shap"}.issubset(df.columns) and not df.empty:
            st.bar_chart(df.set_index("feature")["mean_abs_shap"])