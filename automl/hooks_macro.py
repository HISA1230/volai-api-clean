# automl/hooks_macro.py
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

SUFFIX = "_m"  # 右（macro）由来の重複列につけるサフィックス

def _to_utc_naive(series) -> pd.Series:
    """
    任意の日時列を UTC に正規化してから tz情報を落とした naive に統一。
    """
    dt = pd.to_datetime(series, errors="coerce", utc=True)
    return dt.dt.tz_localize(None)

def attach_macro_features(
    df: pd.DataFrame,
    engine_url: str,
    on_col: str = "date",
    method: str = "asof",           # "asof" / "nearest" / "exact"
    max_lag_days: int | None = 7,   # 許容する過去（asof）や近傍（nearest）の最大日数
) -> pd.DataFrame:
    """
    df の on_col をキーに macro_features を結合。
      - method="asof"   : 直近過去の営業日に遡ってマッチ（週末ズレ吸収）
      - method="nearest": 近い日付に双方向でマッチ（テストや分散確保に便利）
      - method="exact"  : 等値JOIN
    """
    if on_col not in df.columns:
        return df

    engine = create_engine(engine_url, future=True)
    try:
        macro = pd.read_sql("SELECT * FROM macro_features ORDER BY date", engine)
    except Exception:
        return df
    if macro.empty or "date" not in macro.columns:
        return df

    left = df.copy()

    # 🔧 日時キーを UTC→naive に統一
    left[on_col]  = _to_utc_naive(left[on_col])
    macro["date"] = _to_utc_naive(macro["date"])

    left_valid  = left[left[on_col].notna()].copy()
    macro_valid = macro[macro["date"].notna()].copy()
    if left_valid.empty or macro_valid.empty:
        return df

    # ---- asof / nearest: merge_asof ベース ----
    if method in ("asof", "nearest"):
        left_sorted  = left_valid.sort_values(on_col).reset_index().rename(columns={"index": "_orig_idx"})
        macro_sorted = macro_valid.sort_values("date")

        direction = "backward" if method == "asof" else "nearest"
        merged = pd.merge_asof(
            left_sorted,
            macro_sorted,
            left_on=on_col,
            right_on="date",
            direction=direction,
            suffixes=("", SUFFIX),
        )

        # 古すぎるマッチは NaN に（asof は過去方向の差、nearest は絶対差）
        if max_lag_days is not None:
            if method == "asof":
                lag_days = (merged[on_col] - merged["date"]).dt.days
                too_far = lag_days > max_lag_days
            else:  # nearest
                lag_days_abs = (merged[on_col] - merged["date"]).abs().dt.days
                too_far = lag_days_abs > max_lag_days

            macro_cols = [c for c in macro_sorted.columns if c != "date"]
            merged.loc[too_far, macro_cols] = np.nan

        # 右の date は不要（on_col を優先）
        if "date" in merged.columns and on_col != "date":
            merged.drop(columns=["date"], inplace=True, errors="ignore")

        # ✅ 新規列だけを out に追加（元のインデックスへ復元）
        merged.set_index("_orig_idx", inplace=True)
        out = left.copy()
        new_cols = [c for c in merged.columns if c not in out.columns]
        if new_cols:
            out.loc[merged.index, new_cols] = merged[new_cols].values
        return out

    # ---- exact: 等値JOIN ----
    if method == "exact":
        merged = left.merge(
            macro_valid,
            left_on=on_col,
            right_on="date",
            how="left",
            suffixes=("", SUFFIX),
        )
        if "date" in merged.columns and on_col != "date":
            merged.drop(columns=["date"], inplace=True, errors="ignore")
        return merged

    # 未知の method の場合は asof にフォールバック
    return attach_macro_features(df, engine_url, on_col=on_col, method="asof", max_lag_days=max_lag_days)