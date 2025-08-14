# strategy_ui.py（SHAP可視化＋再計算＋モデルアーカイブ＋メタ編集＋サイドバー認証 完全版）
import os
import joblib
import requests
import pandas as pd
import altair as alt
import shap
import matplotlib.pyplot as plt
import streamlit as st
import requests, streamlit as st, pandas as pd, os

# =========================
# 基本設定
# =========================
st.set_page_config(layout="wide")
st.title("📈 高精度ボラ予測AIアプリ Ver.2030")
API_BASE_URL = "http://127.0.0.1:8888"

# =========================
# 🔐 サイドバー：簡易ログイン
# =========================
st.sidebar.subheader("🔐 ログイン")
email = st.sidebar.text_input("Email", value="test@example.com")
password = st.sidebar.text_input("Password", type="password", value="test1234")

if st.sidebar.button("Sign in"):
    try:
        res = requests.post(f"{API_BASE_URL}/login", json={"email": email, "password": password})
        if res.status_code == 200:
            token = res.json().get("access_token")
            if token:
                st.session_state["access_token"] = token
                st.sidebar.success("ログイン成功！")
            else:
                st.sidebar.error("トークンが取得できませんでした")
        else:
            st.sidebar.error(f"ログイン失敗: {res.status_code} - {res.text}")
    except Exception as e:
        st.sidebar.error(f"通信エラー: {e}")

with st.sidebar.expander("🔑 手動でトークンを設定（Swaggerで取得したものを貼り付け可）"):
    manual_token = st.text_input("Bearer Token", type="password", placeholder="eyJhbGciOi...")
    if st.button("Use this token"):
        if manual_token:
            st.session_state["access_token"] = manual_token
            st.sidebar.success("トークン設定しました")

def get_headers():
    token = st.session_state.get("access_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}

# =========================
# 🔍 モデル選択（APIから取得・既定モデルを初期選択）
# =========================
st.subheader("🔍 モデル選択（SHAP解析）")

def fetch_models():
    try:
        r = requests.get(f"{API_BASE_URL}/models", headers=get_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            st.warning("認証が必要です。左の『ログイン』からサインインしてください。")
        else:
            st.error(f"取得エラー: {r.status_code} - {r.text}")
    except Exception as e:
        st.error(f"通信エラー: {e}")
    return {"default_model": "", "models": []}

def fetch_default_model():
    # 念のため冗長に既定モデル単独取得
    try:
        r = requests.get(f"{API_BASE_URL}/models/default", headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return r.json().get("default_model")
    except Exception:
        pass
    return ""

models_payload = fetch_models()
models_list = models_payload.get("models", [])
api_default_model = models_payload.get("default_model") or fetch_default_model()

if models_list:
    option_labels = [m["name"] for m in models_list]  # 表示名（ファイル名）
    option_values = [m["path"] for m in models_list]  # 実体パス
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

if st.button("🌀 SHAP特徴量重要度を表示"):
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

if st.button("📊 SHAPを再計算して保存"):
    try:
        payload = {
            "model_path": selected_model_path,
            "sample_size": int(recompute_sample),
            "feature_cols": ["rci", "atr", "vix"],
        }
        res = requests.post(
            f"{API_BASE_URL}/predict/shap/recompute",
            json=payload,
            headers=get_headers(),
            timeout=30,
        )

        if res.status_code == 200:
            data = res.json()
            st.success(f"✅ {data['message']}")
            st.write(f"- shap_values: `{data['shap_values_path']}`")
            st.write(f"- summary_csv: `{data['summary_csv_path']}`")
            st.write(f"- 上位特徴量: {data.get('top_features')}")
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

# 🔎 検索/フィルタ UI
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

        r = requests.get(f"{API_BASE_URL}/models", params=params, headers=get_headers(), timeout=15)
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
    if st.button("🔄 再読み込み"):
        st.rerun()

# ← 検索条件を渡して取得
models_payload = fetch_models_safe(q, selected_tag)
default_model = models_payload.get("default_model", "")
models_list = models_payload.get("models", [])

if not models_list:
    st.info("models/ に *.pkl が見つかりません。再学習やファイル配置を行ってください。")
else:
    df = pd.DataFrame(models_list)

    # 追加列（存在すれば表示）
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
        if st.button("⭐ 既定に設定"):
            try:
                r = requests.post(f"{API_BASE_URL}/models/default",
                                  json={"model_path": selected_path},
                                  headers=get_headers(), timeout=15)
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
        if st.button("✏️ リネーム"):
            if new_name.strip():
                try:
                    r = requests.post(f"{API_BASE_URL}/models/rename",
                                      json={"old_name": selected_name, "new_name": new_name},
                                      headers=get_headers(), timeout=15)
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
            if st.button("🗑️ 削除") and confirm:
                try:
                    r = requests.delete(f"{API_BASE_URL}/models",
                                        json={"model_path": selected_path},
                                        headers=get_headers(), timeout=15)
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
# 📝 A-29: モデルのメタ情報 編集UI
# =========================
st.header("📝 モデルのメタ情報 編集")

def _fetch_models_for_meta():
    try:
        r = requests.get(f"{API_BASE_URL}/models", headers=get_headers(), timeout=15)
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
        r = requests.get(f"{API_BASE_URL}/models/meta",
                         params={"model_path": sel_path_meta},
                         headers=get_headers(), timeout=15)
        meta = r.json().get("meta", {}) if r.status_code == 200 else {}
    except Exception:
        meta = {}

    # 既存メタをフォーム初期値に
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
        if st.button("💾 メタ情報を保存"):
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
                r = requests.post(f"{API_BASE_URL}/models/meta",
                                  json=body, headers=get_headers(), timeout=15)
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
        if st.button("👀 現在のメタをプレビュー"):
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

# ⭐ 既定モデルのカード強調（メタ表示）
default_model_for_card = models_payload.get("default_model") or fetch_default_model()
if default_model_for_card:
    try:
        r = requests.get(f"{API_BASE_URL}/models/meta",
                         params={"model_path": default_model_for_card},
                         headers=get_headers(), timeout=10)
        meta = r.json().get("meta", {}) if r.status_code == 200 else {}
    except Exception:
        meta = {}

    st.divider()
    st.subheader("⭐ 既定モデル")
    st.markdown(f"**Path:** `{default_model_for_card}`")
    if meta:
        st.markdown(f"- **表示名**: {meta.get('display_name') or '—'}")
        st.markdown(f"- **バージョン**: {meta.get('version') or '—'}")
        st.markdown(f"- **オーナー**: {meta.get('owner') or '—'}")
        st.markdown(f"- **タグ**: {', '.join(meta.get('tags', [])) or '—'}")
        st.markdown(f"- **説明**: {meta.get('description') or '—'}")
    else:
        st.info("メタ情報が未登録です。上の『モデルのメタ情報 編集』から登録できます。")
        
# =========================
# 🔬 モデル比較モード（MAE & SHAPサイドバイサイド）
# =========================
st.divider()
st.header("🔬 モデル比較モード")

def _fetch_models_list():
    try:
        r = requests.get(f"{API_BASE_URL}/models", headers=get_headers(), timeout=15)
        if r.status_code == 200:
            payload = r.json()
            return payload.get("models", []), payload.get("default_model", "")
    except Exception:
        pass
    return [], ""

models_list, default_model_path = _fetch_models_list()
if not models_list:
    st.info("モデル一覧を取得できませんでした（未ログイン or モデルがありません）。左のログイン後、モデルを作成/再学習してください。")
else:
    names = [m["name"] for m in models_list]
    paths = [m["path"] for m in models_list]
    name_to_path = {n: p for n, p in zip(names, paths)}

    colA, colB = st.columns(2)
    with colA:
        selA = st.selectbox("Model A", names, index=0 if names else 0)
    with colB:
        # 既定モデルをデフォルトにすると便利
        idx_default = names.index(os.path.basename(default_model_path)) if default_model_path and os.path.basename(default_model_path) in names else (1 if len(names) > 1 else 0)
        selB = st.selectbox("Model B", names, index=idx_default)

    pathA = name_to_path.get(selA)
    pathB = name_to_path.get(selB)

    # --- MAE比較（prediction_logsから）
    st.subheader("📈 精度比較（MAE）")
    try:
        r = requests.get(f"{API_BASE_URL}/predict/logs", headers=get_headers(), timeout=15)
        if r.status_code == 200:
            logs = r.json()
            if not logs:
                st.warning("予測ログがありません。/predict を実行してから比較してください。")
            else:
                df_logs = pd.DataFrame(logs)
                # abs_error が入っている行のみ
                df_mae = df_logs[df_logs["abs_error"].notnull()]
                # ない場合もあるので防御
                if df_mae.empty:
                    st.info("誤差（abs_error）がまだありません。/predict/actual で正解ラベルを登録してください。")
                else:
                    g = df_mae.groupby("model_path").agg(
                        MAE=("abs_error", "mean"),
                        N=("abs_error", "count")
                    ).reset_index()

                    maeA = g[g["model_path"] == pathA]["MAE"].values[0] if (pathA in set(g["model_path"])) else None
                    maeB = g[g["model_path"] == pathB]["MAE"].values[0] if (pathB in set(g["model_path"])) else None
                    nA   = g[g["model_path"] == pathA]["N"].values[0]   if (pathA in set(g["model_path"])) else 0
                    nB   = g[g["model_path"] == pathB]["N"].values[0]   if (pathB in set(g["model_path"])) else 0

                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric(f"{selA}（N={nA}）", f"{maeA:.4f}" if maeA is not None else "—")
                    with c2:
                        st.metric(f"{selB}（N={nB}）", f"{maeB:.4f}" if maeB is not None else "—")

                    # 並べて表でも確認
                    show = []
                    show.append({"model": selA, "path": pathA, "MAE": f"{maeA:.4f}" if maeA is not None else "—", "N": nA})
                    show.append({"model": selB, "path": pathB, "MAE": f"{maeB:.4f}" if maeB is not None else "—", "N": nB})
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

        # Altairで左右に並べる
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
            
    BASE_URL = "http://127.0.0.1:8888"

def auth_headers():
    tok = st.session_state.get("access_token")  # 既存のログイン処理で保存済み想定
    return {"Authorization": f"Bearer {tok}"} if tok else {}

st.divider()
st.subheader("📆 スケジューラ & SHAP")

# 既定モデル表示
col1, col2 = st.columns([1,1])
with col1:
    if st.button("🔄 既定モデルを取得"):
        r = requests.get(f"{BASE_URL}/models/default", headers=auth_headers())
        if r.ok:
            st.success(r.json().get("default_model", "not set"))
            st.session_state["default_model"] = r.json()["default_model"]
        else:
            st.error(r.text)

with col2:
    # SHAP再計算
    mp = st.session_state.get("default_model")
    st.caption(f"SHAP再計算対象: {mp or '(未取得)'}")
    if st.button("♻️ SHAP再計算"):
        if not mp:
            st.warning("先に既定モデルを取得してください。")
        else:
            r = requests.post(f"{BASE_URL}/predict/shap/recompute",
                              headers={**auth_headers(), "Content-Type":"application/json"},
                              json={"model_path": mp})
            st.write(r.json() if r.ok else r.text)

# スケジューラ実行フォーム
with st.form("scheduler_run"):
    st.write("🧪 条件付き評価・再学習・昇格（A-30 実行）")
    mae = st.number_input("MAEしきい値", value=0.008, step=0.001, format="%.3f")
    mnl = st.number_input("最小ラベル数（昇格の下限）", min_value=0, value=10, step=1)
    topk = st.number_input("Top-K", min_value=1, value=3, step=1)
    ap  = st.checkbox("自動昇格を有効化", value=True)
    note= st.text_input("メモ", value="manual run")
    run = st.form_submit_button("▶ 実行")
    if run:
        r = requests.post(f"{BASE_URL}/scheduler/run",
                          headers={**auth_headers(), "Content-Type":"application/json"},
                          json={"mae_threshold": float(mae),
                                "min_new_labels": int(mnl),
                                "top_k": int(topk),
                                "auto_promote": bool(ap),
                                "note": note})
        st.write(r.json() if r.ok else r.text)

# 履歴
if st.button("📜 履歴を更新"):
    r = requests.get(f"{BASE_URL}/scheduler/status", headers=auth_headers())
    if r.ok:
        val = r.json().get("value", [])
        df = pd.DataFrame(val)
        st.dataframe(df if not df.empty else pd.DataFrame([{"message":"no history"}]))
    else:
        st.error(r.text)

# SHAPサマリ軽表示（既定モデル名から推定）
mp = st.session_state.get("default_model")
if mp:
    csv_guess = os.path.join("models", os.path.basename(mp).replace(".pkl", "_shap_summary.csv"))
    if os.path.exists(csv_guess):
        st.caption(f"SHAP summary: {csv_guess}")
        df = pd.read_csv(csv_guess)
        st.bar_chart(df.set_index("feature")["mean_abs_shap"])