from __future__ import annotations

import json
import subprocess
import sys
import os
from typing import List, Optional, Dict, Any
from datetime import datetime

import pandas as pd
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from build.feature_builder import FeatureBuilder

app = FastAPI(title="Volatility AI API", version="0.1.3")

# ---- 静的ファイル（favicon など）の配信設定：app 生成直後がベスト ----
# 例: app/static/favicon.ico があれば /static/favicon.ico で配信されます
STATIC_DIR = os.path.join(os.getcwd(), "app", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# =========================
# Pydantic models
# =========================
class PredictResponse(BaseModel):
    horizon: int
    n: int
    predictions: List[float]


# UI が期待する “latest” の形（緩め：dict返却でもOKだが、ここでは型を用意）
class LatestItem(BaseModel):
    ts_utc: str
    time_band: str
    sector: str
    size: str
    symbol: str
    pred_vol: float
    fake_rate: float
    confidence: float
    rec_action: str
    comment: str


# ログ（将来DB化する前の最小）
class LogItem(BaseModel):
    ts_utc: str
    owner: str
    time_band: str
    sector: str
    size: str
    symbol: str
    pred_vol: float
    fake_rate: float
    confidence: float
    rec_action: str
    comment: str


class ModelService:
    def __init__(self):
        self.ready = False

    def predict(self, X: pd.DataFrame) -> List[float]:
        # TODO: ここを本物のモデル推論に置き換える
        return [0.0] * len(X)


model_svc = ModelService()


# =========================
# Helpers
# =========================
def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _dummy_latest(n: int = 100) -> List[Dict[str, Any]]:
    """DBが空のとき UI に表示を出すためのダミー（最小2件）"""
    now = _now_iso()
    rows = [
        {
            "ts_utc": now,
            "time_band": "A",
            "sector": "tech",
            "size": "Small",
            "symbol": "NVDA",
            "pred_vol": 0.012,
            "fake_rate": 0.24,
            "confidence": 0.68,
            "rec_action": "WATCH",
            "comment": "DBが空のためダミー表示（確認用）",
        },
        {
            "ts_utc": now,
            "time_band": "A",
            "sector": "energy",
            "size": "Mid",
            "symbol": "XOM",
            "pred_vol": 0.010,
            "fake_rate": 0.18,
            "confidence": 0.72,
            "rec_action": "WATCH",
            "comment": "DBが空のためダミー表示（確認用）",
        },
    ]
    # nが小さければ切る
    return rows[: max(1, min(int(n), 1000))]


# =========================
# Routes
# =========================
@app.get("/health")
def health():
    return {"status": "ok"}


# ---- UI が叩くエンドポイント（ここが今回の追加） ----
@app.get("/api/predict/latest", response_model=List[LatestItem], tags=["api"])
def api_predict_latest(n: int = 100, mode: Optional[str] = None):
    """
    UI 用：最新予測を返す（まずはダミー）。
    将来: DB から SELECT、または推論結果を返す。
    """
    # 現段階では DB が空なので常にダミー
    return _dummy_latest(n=n)


@app.get("/api/predict/ping", tags=["api"])
def api_predict_ping():
    return {"status": "ok", "ts_utc": _now_iso()}


@app.get("/api/predict/logs", response_model=List[LogItem], tags=["api"])
def api_predict_logs(n: int = 2000, limit: int = 2000, owner: Optional[str] = None):
    """
    UI 用：ログ一覧（当面は空 or ダミー）。
    将来: DB の prediction_log などから返す。
    """
    # まずは空（UI側は「まだログがない」表示になる）
    # ダミーを入れたいなら return で1件返してもOK
    return []


# ---- 既存の feature/predict ルート（あなたの元コードを維持） ----
@app.get("/features/debug")
def features_debug(start: str | None = None, end: str | None = None):
    fb = FeatureBuilder()
    # 1回の materialize で派生も含めて構築
    all_df = fb.materialize(start=start, end=end)
    out = []
    for f in fb.features:
        name = f.get("name")
        provider = str(f.get("provider", "fmp"))
        endpoint = f.get("endpoint", "(derived)")
        try:
            if provider == "derived":
                df = all_df[all_df["name"] == name] if all_df is not None and not all_df.empty else pd.DataFrame()
            else:
                tmp = fb._build_one(f, start, end)
                df = tmp if tmp is not None else pd.DataFrame()

            rows = int(len(df))
            tail = None
            if rows > 0:
                dfx = df.tail(3).copy()
                if "date" in dfx.columns:
                    dfx["date"] = dfx["date"].astype(str)
                tail = dfx.to_dict(orient="records")

            out.append({
                "name": name,
                "provider": provider,
                "ok": rows > 0,
                "rows": rows,
                "endpoint": endpoint,
                "sample_tail": tail,
                "note": ""
            })
        except Exception as e:
            out.append({
                "name": name,
                "provider": provider,
                "ok": False,
                "rows": 0,
                "endpoint": endpoint,
                "sample_tail": None,
                "note": str(e)
            })
    return {"features": out}


@app.get("/predict", response_model=PredictResponse)
def predict(symbol: str = "SPY", horizon: int = 1, start: str | None = None, end: str | None = None):
    fb = FeatureBuilder()
    feats = fb.materialize(start=start, end=end)
    if feats is None or feats.empty:
        last_date = pd.Timestamp.today().normalize()
        wide = pd.DataFrame({"bias": [1.0]}, index=[last_date])
    else:
        last_date = feats["date"].max()
        wide = (
            feats[feats["date"] == last_date]
            .pivot_table(index="date", columns="name", values="value")
            .fillna(0.0)
        )
        if wide.empty:
            wide = pd.DataFrame({"bias": [1.0]}, index=[last_date])
    yhat = model_svc.predict(wide)
    return PredictResponse(horizon=horizon, n=len(yhat), predictions=yhat)


# --- Re-added feature endpoints ---
@app.get("/features/last")
def features_last(start: str | None = None, end: str | None = None):
    fb = FeatureBuilder()
    df = fb.materialize(start=start, end=end)
    if df is None or df.empty:
        return {"rows": 0, "columns": [], "data": []}
    wide = (
        df.pivot_table(index="date", columns="name", values="value")
          .sort_index()
          .ffill()
    )
    if wide.empty:
        return {"rows": 0, "columns": [], "data": []}
    last_date = wide.index.max()
    rec = wide.loc[last_date].to_dict()
    rec["date"] = str(last_date)
    cols = ["date"] + list(wide.columns)
    return {"rows": 1, "columns": cols, "data": [rec]}


@app.get("/features/last_flat")
def features_last_flat(start: str | None = None, end: str | None = None):
    # 仕様は last と同じフラット行を返す
    return features_last(start=start, end=end)


@app.get("/features/schema")
def features_schema():
    # FeatureBuilderに features 属性が無い環境でも落ちないように防御
    feats = []
    try:
        fb = FeatureBuilder()
        for f in getattr(fb, "features", []):
            feats.append({
                "name": f.get("name"),
                "provider": f.get("provider", "unknown"),
                "freq": f.get("freq", "D"),
            })
    except Exception:
        pass
    return {"count": len(feats), "features": feats, "model_columns": []}


@app.get("/features/preview")
def features_preview(start: str | None = None, end: str | None = None):
    out = features_last(start=start, end=end)
    if isinstance(out, dict) and "data" not in out:
        out["data"] = []
    return out


@app.post("/train/trigger")
def train_trigger():
    # python -m build.train を実行（tests は subprocess.run を monkeypatch します）
    cmd = [sys.executable, "-m", "build.train"]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    out = {"returncode": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}
    # 標準出力が JSON ならマージして返す
    try:
        parsed = json.loads(cp.stdout)
        if isinstance(parsed, dict):
            out.update(parsed)
    except Exception:
        pass
    return out
