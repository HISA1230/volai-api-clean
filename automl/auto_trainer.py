# automl/auto_trainer.py
import os
import joblib
import shap
import pandas as pd
import numpy as np

from sklearn.linear_model import Ridge
from sklearn.dummy import DummyRegressor
import lightgbm as lgb

from sqlalchemy import text
from database.database_user import engine
from automl.hooks_macro import attach_macro_features


class AutoTrainer:
    """
    - DBから学習データを取得（prediction_logs）
    - 日付列を自動推定して `date` を生成 → macro_features を LEFT JOIN（as-of）
    - 相関トップKで特徴選抜（全数値列から可）
    - 小標本は Ridge にフォールバック／十分なら LightGBM
    - モデル & SHAP/係数重要度 保存
    """

    def __init__(
        self,
        data_path: str | None = None,
        model_path: str = "models/vol_model.pkl",
        feature_cols: list[str] | None = None,
        label_col: str = "actual_volatility",
    ):
        self.data_path = data_path
        self.model_path = model_path
        self.feature_cols = feature_cols or ["rci", "atr", "vix"]  # 初期候補
        self.label_col = label_col

        self.df: pd.DataFrame | None = None
        self.data: pd.DataFrame | None = None
        self.model = None

        self.engine_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://postgres:postgres1234@localhost:5432/volatility_ai",
        )

    # ---------- 内部: 日付列の自動推定 ----------
    @staticmethod
    def _ensure_date_column(df: pd.DataFrame) -> pd.DataFrame:
        """
        df 内に date が無い場合、よくある日時列から date を生成する。
        優先順: 'date','logged_at','created_at','ran_at','ts','timestamp','time','datetime'
        """
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
            return df

        candidates = ["logged_at", "created_at", "ran_at", "ts", "timestamp", "time", "datetime"]
        for c in candidates:
            if c in df.columns:
                dt = pd.to_datetime(df[c], errors="coerce")
                if dt.notna().any():
                    df["date"] = dt.dt.date
                    return df
        return df  # 見つからなければそのまま

    # ----------------------------
    # データ取得（macro_features 自動結合つき）
    # ----------------------------
    def load_data_from_db(self):
        with engine.connect() as conn:
            base_q = f"SELECT * FROM prediction_logs WHERE {self.label_col} IS NOT NULL"
            df_raw = pd.read_sql(text(base_q), conn)

        if df_raw.empty:
            raise ValueError("prediction_logs に学習用データがありません。")
        if self.label_col not in df_raw.columns:
            raise ValueError(f"label_col '{self.label_col}' が prediction_logs に存在しません。")

        # リーク/メタ列除外（候補から）
        leak_cols = {"predicted_volatility", "abs_error", "model_path"}
        meta_cols = {"id", "user_id", "uid", "email"}

        # まず全列保持（dateは後で生成）、リークは外す
        base_cols = [c for c in df_raw.columns if c not in leak_cols]
        df = df_raw[base_cols].copy()

        # 日付列を自動生成（なければJOINはスキップ）
        df = self._ensure_date_column(df)

        # macro_features を LEFT JOIN（存在する場合のみ／as-of は hooks_macro 側の既定）
        if "date" in df.columns:
            df = attach_macro_features(
                df,
                engine_url=self.engine_url,
                on_col="date",
                method="nearest",   # ← お試し
                max_lag_days=3
            )

        # 数値列の抽出（labelは別扱い）
        numeric_cols = [c for c in df.columns if c != "date" and pd.api.types.is_numeric_dtype(df[c])]
        # 初期候補の型も数値に寄せて含める
        for c in self.feature_cols:
            if c in df.columns and c not in numeric_cols:
                df[c] = pd.to_numeric(df[c], errors="coerce")
                if pd.api.types.is_numeric_dtype(df[c]):
                    numeric_cols.append(c)

        # ラベルも数値化
        df[self.label_col] = pd.to_numeric(df[self.label_col], errors="coerce")

        # 候補＝数値列からメタ/ラベル除外
        candidate_feats = [c for c in numeric_cols if c not in meta_cols and c != self.label_col]
        # 標本数2未満の列は弾く（相関計算できないため）
        candidate_feats = [c for c in candidate_feats if df[c].count() >= 2]

        if not candidate_feats:
            fallback = [c for c in self.feature_cols if c in df.columns and df[c].count() >= 2]
            if not fallback:
                raise ValueError("数値の候補特徴量が見つかりません。")
            candidate_feats = fallback

        # 行は落とさない（LGBMはNaN可）。ただしラベルNaNは落とす。
        df = df.dropna(subset=[self.label_col])

        use_cols = candidate_feats + [self.label_col]
        df = df[use_cols]

        if df.empty or len(df) < 2:
            raise ValueError("学習用データが不足しています（2行未満）。")

        self.df = df
        self.data = df
        return df

    # ----------------------------
    # 特徴量選別（相関トップK）
    # ----------------------------
    def filter_top_features(self, top_k: int = 3, use_all_numeric: bool = True, ensure_include: list[str] | None = None):
        if self.df is None or self.df.empty:
            raise ValueError("データが読み込まれていません（dfが空）")

        if use_all_numeric:
            candidate = [c for c in self.df.columns if c != self.label_col]
        else:
            candidate = [c for c in self.feature_cols if c in self.df.columns] or \
                        [c for c in self.df.columns if c != self.label_col]

        corr = (
            self.df[candidate + [self.label_col]]
            .corr(numeric_only=True)[self.label_col]
            .abs()
            .sort_values(ascending=False)
        )
        ranked = [c for c in corr.index if c != self.label_col]

        # まずは相関順で top_k
        top_features = ranked[: max(1, int(top_k))]

        # ensure_include を優先採用（存在する場合）
        ensure_include = ensure_include or []
        for f in ensure_include:
            if f in candidate and f not in top_features:
                top_features.append(f)

        # 重複除去しつつ top_k にトリム
        seen = set()
        ordered = []
        for f in top_features:
            if f not in seen:
                ordered.append(f); seen.add(f)
        self.feature_cols = ordered[: max(1, int(top_k))]
        return self.feature_cols

    # ----------------------------
    # 学習（小標本は線形へフォールバック）
    # ----------------------------
    def train_new_model(self, shap_sample_size: int = 512, linear_fallback_n: int = 25):
        """
        小標本（例: 行数 < linear_fallback_n）なら Ridge にフォールバック。
        それ以上は LGBM（列/行サンプリングで多様化）で学習。
        """
        if self.df is None or self.df.empty:
            raise ValueError("学習用データがありません。load_data_from_db() を先に呼んでください。")

        X = self.df[self.feature_cols].copy()
        y = self.df[self.label_col].copy()

        # 極小標本は平均モデル
        if len(X) < 2:
            self.model = DummyRegressor(strategy="mean")
            self.model.fit(X, y)
            self._save_model_and_optional_shap(X=None, shap_values=None)
            return

        # 小標本は線形回帰（Ridge）
        if len(X) < int(linear_fallback_n):
            self.model = Ridge(alpha=1.0)
            # Ridge は NaN を許容しないため、中央値で単純補完
            X_fit = X.fillna(X.median(numeric_only=True))
        else:
            # 標本が十分なら LGBM（多様化設定; NaN OK）
            self.model = lgb.LGBMRegressor(
                n_estimators=400,
                learning_rate=0.05,
                num_leaves=8,
                feature_fraction=0.7,
                bagging_fraction=0.8,
                bagging_freq=1,
                min_data_in_leaf=1,
                random_state=42,
            )
            X_fit = X  # LGBMはNaN可

        # 学習
        self.model.fit(X_fit, y)

        # SHAP（重いのでサンプル）— Ridge でも LGBM でも同じ取り回しでOK
        X_use = X_fit.sample(min(len(X_fit), shap_sample_size), random_state=42)
        shap_values = None
        try:
            explainer = shap.Explainer(self.model, X_use)
            shap_values = explainer(X_use)
        except Exception as e:
            print(f"⚠️ SHAP計算スキップ: {e}")

        self._save_model_and_optional_shap(X_use, shap_values)

    # ----------------------------
    # 保存（モデル & SHAP/係数重要度）
    # ----------------------------
    def _save_model_and_optional_shap(self, X: pd.DataFrame | None, shap_values):
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.dump(self.model, self.model_path)

        base = os.path.splitext(self.model_path)[0]
        shap_values_path = f"{base}_shap_values.pkl"
        shap_summary_path = f"{base}_shap_summary.csv"
        compat_summary_path = "models/shap_summary.csv"
        coef_summary_path = f"{base}_coef_summary.csv"  # Ridge係数の重要度

        # --- SHAP 保存 ---
        if shap_values is not None and X is not None and not X.empty:
            try:
                joblib.dump(shap_values, shap_values_path)
                try:
                    mean_abs = shap_values.abs.mean(0).values
                except Exception:
                    mean_abs = np.mean(np.abs(shap_values.values), axis=0)
                shap_df = (
                    pd.DataFrame({"feature": list(X.columns), "mean_abs_shap": mean_abs})
                    .sort_values("mean_abs_shap", ascending=False)
                )
                shap_df.to_csv(shap_summary_path, index=False)
                shap_df.to_csv(compat_summary_path, index=False)
                print(f"✅ SHAP saved: {shap_values_path}, {shap_summary_path}")
            except Exception as e:
                print(f"⚠️ SHAP保存スキップ: {e}")
        else:
            if X is not None and not X.empty:
                shap_df = pd.DataFrame({"feature": list(X.columns), "mean_abs_shap": 0.0})
                shap_df.to_csv(shap_summary_path, index=False)
                shap_df.to_csv(compat_summary_path, index=False)
                print("⚠️ SHAP未計算のため、0埋めの shap_summary.csv を出力しました。")

        # --- 係数ベース重要度（Ridge のとき） ---
        try:
            if isinstance(self.model, Ridge) and X is not None and not X.empty:
                coefs = getattr(self.model, "coef_", None)
                if coefs is not None and len(coefs) == X.shape[1]:
                    stds = X.std(ddof=0).replace(0, np.nan)  # 0分散はNaNに
                    imp = np.abs(coefs) * stds.values
                    coef_df = (
                        pd.DataFrame({
                            "feature": list(X.columns),
                            "coef_abs": np.abs(coefs),
                            "std": stds.values,
                            "coef_importance": imp
                        })
                        .sort_values("coef_importance", ascending=False)
                    )
                    coef_df.to_csv(coef_summary_path, index=False)
                    print(f"✅ Coef summary saved: {coef_summary_path}")
        except Exception as e:
            print(f"⚠️ coef_summary 出力スキップ: {e}")

    # ----------------------------
    # 明示保存
    # ----------------------------
    def save_model(self, path: str | None = None):
        path = path or self.model_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(self.model, path)