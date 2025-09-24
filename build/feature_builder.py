from dataclasses import dataclass
import pandas as pd

@dataclass
class FeatureBuilder:
    # /features/schema 用の簡易メタデータ
    features = [
        {"name": "vix",          "provider": "fmp",  "freq": "D"},
        {"name": "us10y_yield",  "provider": "fmp",  "freq": "D"},
        {"name": "cpi_yoy",      "provider": "fred", "freq": "M"},
    ]

    def materialize(self, start=None, end=None):
        # 空の DataFrame（列だけ）を返す
        return pd.DataFrame(columns=["date", "name", "value"])