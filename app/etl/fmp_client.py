import os, requests
from typing import Any, Dict, Optional

class FmpClient:
    def __init__(self, api_key: Optional[str] = None, base: str = "https://financialmodelingprep.com/api/v3"):
        self.api_key = api_key or os.environ.get("FMP_API_KEY")
        self.base = base.rstrip("/")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Any:
        if not self.api_key:
            raise RuntimeError("FMP_API_KEY is not set")
        p = dict(params or {})
        p["apikey"] = self.api_key
        url = f"{self.base}/{path.lstrip('/')}"
        r = requests.get(url, params=p, timeout=timeout)
        r.raise_for_status()
        return r.json()
