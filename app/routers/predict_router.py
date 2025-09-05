# app/routers/predict_router.py
# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import os
import math
import logging

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)
logger.info(f"[predict_router] loaded from: {__file__}")

# マクロ特徴量（無くても起動はできるように）
try:
    from app.features.macro_features import MacroFeatureBuilder
    _macro_builder = MacroFeatureBuilder()
except Exception as e:
    _macro_builder = None
    logger.warning("MacroFeatureBuilder の読み込みに失敗（フォールバックで続行）: %s", e)

# joblib は任意（無くても起動だけはできる）
try:
    from joblib import load as joblib_load
except Exception:
    joblib_load = None
    logger.warning("joblib が見つかりません。モデルはフォールバック合成で動作します。")

router = APIRouter(prefix="/api/predict", tags=["predict"])

# ===== 環境・DB =====
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.warning("DATABASE_URL 未設定。/api/predict/latest は DB に接続できません。")
_engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None

# ===== モデル管理 =====
@dataclass
class ModelPaths:
    vol_path: str = "models/vol_model.pkl"
    fake_path: str = "models/fake_model.pkl"

def _align_to_model_features(X: pd.DataFrame, model) -> pd.DataFrame:
    """
    model（Pipeline含む）が学習時に見ていた列(feature_names_in_)に X を合わせる。
    - 足りない列は 0.0 で追加
    - 余分な列は落とす
    - 学習時と同じ列順に揃える
    """
    def _candidates(m):
        yield m
        if hasattr(m, "named_steps"):
            for step in m.named_steps.values():
                yield step
        if hasattr(m, "steps"):
            for _, step in m.steps:
                yield step

    names = None
    for obj in _candidates(model):
        if hasattr(obj, "feature_names_in_"):
            names = list(obj.feature_names_in_)
            break
    if names is None:
        return X

    X2 = X.copy()
    for col in names:
        if col not in X2.columns:
            X2[col] = 0.0
    X2 = X2.loc[:, names]
    for c in X2.columns:
        if not np.issubdtype(X2[c].dtype, np.number):
            X2[c] = pd.to_numeric(X2[c], errors="coerce").fillna(0.0)
    return X2

class ModelManager:
    def __init__(self, paths: ModelPaths = ModelPaths()):
        self.paths = paths
        self.vol_model = None
        self.fake_model = None
        self._load()

    def _load(self):
        if os.getenv("VOLAI_SKIP_MODEL_LOAD") == "1":
            logger.warning("環境変数でモデルロードをスキップ（VOLAI_SKIP_MODEL_LOAD=1）")
            return
        if joblib_load is None:
            return
        try:
            if os.path.exists(self.paths.vol_path):
                self.vol_model = joblib_load(self.paths.vol_path)
                logger.info(f"Loaded vol model: {self.paths.vol_path}")
            if os.path.exists(self.paths.fake_path):
                self.fake_model = joblib_load(self.paths.fake_path)
                logger.info(f"Loaded fake model: {self.paths.fake_path}")
        except Exception as e:
            logger.warning(f"モデルロード失敗: {e.__class__.__name__}: {e}", exc_info=False)

    def predict_vol(self, X: pd.DataFrame) -> Optional[np.ndarray]:
        if self.vol_model is None:
            return None
        try:
            X_aligned = _align_to_model_features(X, self.vol_model)
            y = self.vol_model.predict(X_aligned)
            return np.asarray(y, dtype=float)
        except Exception as e:
            logger.exception(f"pred_vol 推論失敗: {e}")
            return None

    def predict_fake(self, X: pd.DataFrame) -> Optional[np.ndarray]:
        if self.fake_model is None:
            return None
        try:
            X_aligned = _align_to_model_features(X, self.fake_model)
            if hasattr(self.fake_model, "predict_proba"):
                proba = np.asarray(self.fake_model.predict_proba(X_aligned))
                return proba[:, -1]
            raw = np.asarray(self.fake_model.predict(X_aligned), dtype=float)
            mn, mx = np.nanmin(raw), np.nanmax(raw)
            return (raw - mn) / (mx - mn) if mx > mn else np.full_like(raw, 0.5, dtype=float)
        except Exception as e:
            logger.exception(f"fake_rate 推論失敗: {e}")
            return None

model_mgr = ModelManager()

# ===== I/O モデル =====
class PredictItem(BaseModel):
    ts_utc: Optional[str] = None
    time_band: Optional[str] = None
    sector: Optional[str] = None
    size: Optional[str] = None
    pred_vol: Optional[float] = None
    fake_rate: Optional[float] = None
    confidence: Optional[float] = None
    comment: Optional[str] = None
    rec_action: Optional[float] | Optional[str] = None  # 型がブレても落ちないよう緩めに
    symbols: Optional[List[str] | str] = None

# ===== 補助 =====
def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except Exception:
        return None

def _parse_ratio_like(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x)
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except Exception:
            pass
    import re
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if m:
        v = float(m.group(0))
        return v / 100.0 if (1.0 < v <= 100.0) else v
    return None

def _time_band_from_ts(ts_utc: Optional[str]) -> str:
    if not ts_utc:
        return ""
    try:
        h = int(pd.to_datetime(ts_utc, utc=True).hour)
        if 9 <= h < 12:  return "AM"
        if 12 <= h < 15: return "PM"
        return "AH"
    except Exception:
        return ""

# ===== 特徴量組み立て（単一定義！） =====
def build_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    X = pd.DataFrame(index=df.index)

    # 候補列から拾う
    for c in ["avg_score", "avg_sentiment", "平均スコア(色)"]:
        if c in df.columns:
            X["avg_score"] = df[c].map(_parse_ratio_like)
            break
    for c in ["pos_ratio", "ポジ比率"]:
        if c in df.columns:
            X["pos_ratio"] = df[c].map(_parse_ratio_like)
            break
    for c in ["volume", "ボリューム"]:
        if c in df.columns:
            X["news_volume"] = df[c].map(_safe_float)
            break
    for c in ["window_h", "窓[h]"]:
        if c in df.columns:
            X["window_h"] = df[c].map(_safe_float)
            break

    # sector one-hot（トップ10、それ以外は Other）
    sec = df["sector"] if "sector" in df.columns else (df["セクター"] if "セクター" in df.columns else None)
    if sec is not None:
        sec = sec.fillna("Unknown").astype(str)
        top = sec.value_counts().index[:10]
        X = pd.concat([X, pd.get_dummies(sec.where(sec.isin(top), "Other"), prefix="sec")], axis=1)

    # ts_utc → hour
    ts_col = "ts_utc" if "ts_utc" in df.columns else ("時刻" if "時刻" in df.columns else None)
    if ts_col and ts_col in df.columns:
        X["hour"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce").dt.hour.fillna(-1).astype(int)

    # マクロ特徴量
    if ts_col and _macro_builder is not None:
        try:
            X_macro = _macro_builder.build(df[ts_col])
            if isinstance(X_macro, pd.DataFrame) and not X_macro.empty:
                X = pd.concat([X, X_macro], axis=1)
        except Exception as e:
            logger.warning("macro features build failed: %s", e)

    return X.fillna(0.0), {"built_cols": list(X.columns)}

def decide_rec_action(pred_vol: Optional[float], fake_rate: Optional[float], conf: Optional[float]) -> Tuple[str, str]:
    pv, fr, cf = pred_vol or 0.0, fake_rate or 0.0, conf or 0.0
    if fr >= 0.6: return "avoid", "⛔"
    if cf >= 0.7 and fr < 0.3 and pv >= 0.6: return "buy", "🟢📈"
    if cf >= 0.5 and pv >= 0.5 and fr < 0.4: return "watch", "👀"
    return "hold", "🔎"

def fetch_news_sentiment(n: int = 200) -> pd.DataFrame:
    if _engine is None:
        raise RuntimeError("DATABASE_URL が未設定のため、DB に接続できません。")
    sql = text("""
        SELECT * FROM news_sentiment
        ORDER BY ts_utc DESC
        LIMIT :n
    """)
    with _engine.begin() as conn:
        df = pd.read_sql(sql, conn, params={"n": int(n)})
    return df

# ===== 疎通確認 =====
@router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root_ping():
     return {"ok": True, "router": "predict", "file": __file__}

@router.api_route("/ping", methods=["GET", "HEAD"], include_in_schema=False)
def ping():
     return {"ok": True, "router": "predict", "file": __file__}

# ===== 本体 =====
@router.get("/latest", response_model=List[PredictItem])
def get_latest_predictions(n: int = Query(200, ge=1, le=1000)) -> List[Dict[str, Any]]:
    try:
        df = fetch_news_sentiment(n=n)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"DB fetch failed: {e}")

    # symbols 正規化
    if "symbols" in df.columns:
        def _norm_syms(v):
            if v is None or (isinstance(v, float) and math.isnan(v)): return []
            if isinstance(v, list): return [str(x) for x in v]
            return [t.strip() for t in str(v).split(",") if t.strip()]
        df["symbols_norm"] = df["symbols"].map(_norm_syms)
    else:
        df["symbols_norm"] = [[] for _ in range(len(df))]

    # time_band 補完
    if "time_band" not in df.columns:
        ts_col = "ts_utc" if "ts_utc" in df.columns else ("時刻" if "時刻" in df.columns else None)
        df["time_band"] = df[ts_col].map(_time_band_from_ts) if ts_col else ""

    # 特徴量
    X, _info = build_features(df)

    # モデル推論（不足列は predict_* 内で自動補正）
    pred_vol = model_mgr.predict_vol(X)
    fake_rate = model_mgr.predict_fake(X)

    # confidence（暫定）
    if fake_rate is not None:
        conf = np.abs(fake_rate - 0.5) * 2.0
    elif pred_vol is not None:
        conf = np.full(len(X), 0.5)
    else:
        conf = None

    # フォールバック（モデルが無い/失敗時）
    if pred_vol is None:
        base = X.get("avg_score", pd.Series(0.5, index=X.index)).astype(float)
        posr = X.get("pos_ratio", pd.Series(0.5, index=X.index)).astype(float)
        pred_vol = (0.35 + 0.5 * (base * 0.6 + posr * 0.4)).clip(0, 1).to_numpy()
    if fake_rate is None:
        base = X.get("avg_score", pd.Series(0.5, index=X.index)).astype(float)
        fake_rate = (1.0 - base).clip(0, 1).to_numpy()
    if conf is None:
        conf = np.full(len(X), 0.5)

    # numpy → python & clip
    def _san(arr):
        out = []
        for v in arr:
            if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                out.append(None)
            else:
                out.append(float(np.clip(v, 0, 1)))
        return out

    pred_vol = _san(pred_vol)
    fake_rate = _san(fake_rate)
    confidence = _san(conf)

    # 整形
    out: List[Dict[str, Any]] = []
    for i, row in df.reset_index(drop=True).iterrows():
        ts = row.get("ts_utc") or row.get("時刻")
        if isinstance(ts, (pd.Timestamp, datetime)):
            ts_iso = pd.to_datetime(ts, utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            try:
                ts_iso = pd.to_datetime(ts, utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                ts_iso = None

        pv, fr, cf = pred_vol[i], fake_rate[i], confidence[i]
        rec, _emoji = decide_rec_action(pv, fr, cf)

        out.append({
            "ts_utc": ts_iso,
            "time_band": row.get("time_band", _time_band_from_ts(ts_iso)),
            "sector": row.get("sector") or row.get("セクター") or "",
            "size": row.get("size") or "",
            "pred_vol": pv,
            "fake_rate": fr,
            "confidence": cf,
            "comment": row.get("comment") or "",
            "rec_action": rec,
            "symbols": row.get("symbols_norm") or row.get("symbols") or row.get("銘柄") or [],
        })
    return out