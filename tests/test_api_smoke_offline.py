import json
from fastapi.testclient import TestClient
import pandas as pd

from api.main import app
from build.feature_builder import FeatureBuilder

client = TestClient(app)

def _fake_df():
    dates = pd.to_datetime(["2025-09-20", "2025-09-21", "2025-09-22"])
    rows = []
    for name, val in [
        ("vix", 15.0),
        ("gold_change", 0.05),
        ("us10y_yield", 4.10),
    ]:
        for d in dates:
            rows.append({"date": d, "name": name, "value": val})
    return pd.DataFrame(rows)

def test_last_lastflat_preview_offline(monkeypatch):
    # 1) FeatureBuilder.materialize をモック → 外部APIに触らない
    monkeypatch.setattr(FeatureBuilder, "materialize",
                        lambda self, start=None, end=None: _fake_df())

    r = client.get("/features/last")
    assert r.status_code == 200
    js = r.json()
    assert js.get("rows") == 1 and "data" in js

    r = client.get("/features/last_flat")
    assert r.status_code == 200
    js = r.json()
    assert js.get("rows") == 1 and "data" in js

    r = client.get("/features/preview")
    assert r.status_code == 200
    js = r.json()
    assert js.get("rows") == 1 and "data" in js

def test_train_trigger_offline(monkeypatch):
    # 2) subprocess.run をモック → 実トレーニングを走らせない
    class _FakeCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = json.dumps({
                "model": "models/0000.pkl",
                "metrics": {
                    "mse": 1.0, "rmse": 1.0,
                    "baseline_mse": 1.0, "baseline_rmse": 1.0,
                    "start": "2025-01-01 00:00:00", "end": "2025-01-02 00:00:00",
                    "_promoted": True
                }
            })
            self.stderr = ""

    import api.main as mainmod
    monkeypatch.setattr(mainmod.subprocess, "run", lambda *a, **k: _FakeCompleted())

    r = client.post("/train/trigger")
    assert r.status_code == 200
    js = r.json()
    assert js.get("returncode") == 0
    assert "metrics" in js
