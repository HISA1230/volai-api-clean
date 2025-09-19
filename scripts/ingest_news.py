from __future__ import annotations
import os, time, logging
from datetime import datetime
from typing import Dict, Any, List

import requests
from psycopg2.extras import execute_values
from common_db import connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
log = logging.getLogger("news_ingest")

API_KEY = os.environ.get("FMP_API_KEY")
if not API_KEY:
    log.warning("FMP_API_KEY not set. Set it in environment or .env.")

NEWS_URL = "https://financialmodelingprep.com/api/v3/stock_news"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS news_sentiment (
    url           text PRIMARY KEY,
    source        text,
    published_at  timestamptz,
    ticker        text,
    title         text,
    content       text,
    sentiment_score numeric,
    keywords      text[]
);
"""

UPSERT_SQL = """
INSERT INTO news_sentiment (
  url, source, published_at, ticker, title, content, sentiment_score, keywords
) VALUES %s
ON CONFLICT (url) DO UPDATE SET
  source = EXCLUDED.source,
  published_at = EXCLUDED.published_at,
  ticker = EXCLUDED.ticker,
  title = EXCLUDED.title,
  content = EXCLUDED.content,
  sentiment_score = EXCLUDED.sentiment_score,
  keywords = EXCLUDED.keywords
"""

def _get(url: str, params: Dict[str, Any]) -> Any:
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(1 + i); continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("GET failed %s (%s) try=%s", url, e, i+1)
            time.sleep(1 + i)
    raise RuntimeError(f"GET failed: {url}")

def fetch_news(limit: int = 100, tickers: List[str] | None = None) -> List[Dict[str, Any]]:
    params = {"apikey": API_KEY, "limit": limit}
    if tickers: params["tickers"] = ",".join(tickers)
    js = _get(NEWS_URL, params)
    rows = []
    for item in js:
        url = item.get("url")
        if not url: continue
        rows.append({
            "url": url,
            "source": item.get("site"),
            "published_at": item.get("publishedDate"),
            "ticker": item.get("symbol"),
            "title": item.get("title"),
            "content": item.get("text"),
            "sentiment_score": None,
            "keywords": None,
        })
    return rows

def upsert(rows: List[Dict[str, Any]]):
    if not rows:
        log.info("no news"); return
    data = []
    for r in rows:
        ts = None
        if r["published_at"]:
            s = r["published_at"]
            ts = datetime.fromisoformat(s.replace("Z", "+00:00")) if "T" in s else datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        data.append([r["url"], r.get("source"), ts, r.get("ticker"), r.get("title"), r.get("content"), r.get("sentiment_score"), r.get("keywords")])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_SQL)
            execute_values(cur, UPSERT_SQL, data)
        conn.commit()
    log.info("upserted %s news rows", len(data))

def main(limit: int = 200):
    rows = fetch_news(limit=limit)
    upsert(rows)

if __name__ == "__main__":
    main(200)
