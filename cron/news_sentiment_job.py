# cron/news_sentiment_job.py
import os, json, urllib.request
from urllib.parse import urlencode

BASE = os.getenv("BASE_URL", "https://volai-api-02.onrender.com")
EMAIL = os.getenv("VOLAI_EMAIL", "test@example.com")
PASSWORD = os.getenv("VOLAI_PASSWORD", "test1234")
WINDOW_HOURS = int(os.getenv("WINDOW_HOURS", "6"))

def call(path, data=None, headers=None, method=None):
    url = BASE.rstrip("/") + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method or ("POST" if data is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status, res.read().decode()

# 1) login
st, body = call("/login", {"email": EMAIL, "password": PASSWORD},
                {"Content-Type":"application/json"})
token = json.loads(body)["access_token"]

# 2) run job
qs = urlencode({"name":"news_sentiment","window_hours": WINDOW_HOURS})
st, body = call(f"/ops/jobs/run?{qs}", None,
                {"Authorization": f"Bearer {token}"}, "POST")
print(st, body)