from dataclasses import dataclass
import os
import pandas as pd
import yaml

DEFAULT_FEATURES = [
    {"name": "vix", "provider": "fmp", "freq": "D"},
    {"name": "us10y_yield", "provider": "fmp", "freq": "D"},
    {"name": "cpi_yoy", "provider": "fred", "freq": "M"},
]

@dataclass
class FeatureBuilder:
    # 起動時に features を用意（YAML なければデフォルト）
    try:
        _root = os.path.dirname(os.path.dirname(__file__))
        _path = os.path.join(_root, "features", "registry.yaml")
        with open(_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        features = [
            {
                "name": it.get("name"),
                "provider": it.get("provider", "unknown"),
                "freq": it.get("freq", "D"),
            }
            for it in (cfg.get("features") or [])
            if it.get("name")
        ] or DEFAULT_FEATURES
    except FileNotFoundError:
        features = DEFAULT_FEATURES

    def materialize(self, start=None, end=None):
        """
        デモ用：直近3日×全featureのダミー値を返す。
        /features/last は最終日で1行にピボットして返すのでOK。
        """
        today = pd.Timestamp("today").normalize()
        dates = pd.date_range(end=today, periods=3, freq="D")
        rows = []
        for d in dates:
            for i, feat in enumerate(self.features):
                # 適当な連番で値を作る（必要ならロジック調整）
                val = float(i + 1)
                rows.append({"date": d, "name": feat["name"], "value": val})
        return pd.DataFrame(rows)
