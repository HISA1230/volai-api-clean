# app/features/macro_features.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, logging
from typing import Optional
import pandas as pd
import requests

log = logging.getLogger(__name__)
FMP_BASE = "https://financialmodelingprep.com/api/v3"

class MacroFeatureBuilder:
    """
    VIX / US10Y / （代替）S&P500の変化率を時系列に揃えて特徴量化。
    - FMP_API_KEY が無ければ *静かにゼロ埋め* で返す（安全フォールバック）
    - 入力の ts_utc（Series）に対して時間丸め（hour）で forward-fill
    """
    def __init__(self, fmp_api_key: Optional[str] = None, session: Optional[requests.Session] = None):
        self.api_key = fmp_api_key or os.getenv("FMP_API_KEY")
        self.s = session or requests.Session()

    # -------- FMP helpers --------
    def _get(self, url: str, **params):
        if not self.api_key:
            return None
        params = {**params, "apikey": self.api_key}
        try:
            r = self.s.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("FMP fetch failed: %s (%s)", url, e)
            return None

    def _hist_line(self, symbol: str):
        # historical-price-full/<symbol>?serietype=line
        data = self._get(f"{FMP_BASE}/historical-price-full/{symbol}", serietype="line")
        if not data or "historical" not in data:
            return None
        df = pd.DataFrame(data["historical"])
        if "date" not in df or "close" not in df:
            return None
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date").sort_index()
        return df["close"]

    # -------- public: build --------
    def build(self, ts_utc: pd.Series) -> pd.DataFrame:
        # 入力 index に揃える
        ts = pd.to_datetime(ts_utc, utc=True, errors="coerce")
        idx_hour = ts.dt.floor("h")

        # 時間レンジを用意（前後でFFILLできるよう）
        if idx_hour.notna().any():
            rng = pd.date_range(idx_hour.min(), idx_hour.max(), freq="h", tz="UTC")
        else:
            return pd.DataFrame(index=ts_utc.index)

        # 取得（キーが無ければ None → ゼロ埋め）
        s_vix = self._hist_line("%5EVIX")      # ^VIX
        s_tnx = self._hist_line("%5ETNX")      # ^TNX（利回り×10）
        s_spx = self._hist_line("%5EGSPC")     # ^GSPC（ESの代替：変化率だけ使う）

        out = pd.DataFrame(index=rng)

        if s_vix is not None:
            out["macro_vix"] = s_vix.reindex(rng, method="ffill").astype(float)
            out["macro_vix_chg"] = out["macro_vix"].pct_change().fillna(0.0)
        else:
            out["macro_vix"] = 0.0
            out["macro_vix_chg"] = 0.0

        if s_tnx is not None:
            yld = (s_tnx / 10.0).reindex(rng, method="ffill").astype(float)  # ^TNXは×10
            out["macro_us10y"] = yld
            out["macro_us10y_chg"] = yld.diff().fillna(0.0)
        else:
            out["macro_us10y"] = 0.0
            out["macro_us10y_chg"] = 0.0

        if s_spx is not None:
            out["macro_es_chg"] = s_spx.pct_change().reindex(rng, method="ffill").fillna(0.0).astype(float)
        else:
            out["macro_es_chg"] = 0.0

        # 入力行に合わせて返す
        out2 = out.reindex(idx_hour).reset_index(drop=True)
        out2.index = ts_utc.index
        return out2.fillna(0.0)