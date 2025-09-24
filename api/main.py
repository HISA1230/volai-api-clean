from __future__ import annotations
import subprocess, sys, json
import subprocess, sys, json
# -*- coding: utf-8 -*-
from typing import List
from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd

from build.feature_builder import FeatureBuilder

app = FastAPI(title="Volatility AI API", version="0.1.3")

class PredictResponse(BaseModel):
    horizon: int
    n: int
    predictions: List[float]

class ModelService:
    def __init__(self):
        self.ready = False
    def predict(self, X: pd.DataFrame) -> List[float]:
        return [0.0] * len(X)

model_svc = ModelService()

@app.get("/health")
def health():
    return {"status": "ok"}

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
        wide = feats[feats["date"] == last_date].pivot_table(index="date", columns="name", values="value").fillna(0.0)
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

