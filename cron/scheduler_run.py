# cron/scheduler_run.py
import os, json, urllib.request

BASE = os.getenv("BASE_URL", "https://volai-api-02.onrender.com")
payload = {
    "mae_threshold": float(os.getenv("SCHED_MAE", "0.008")),
    "top_k": int(os.getenv("SCHED_TOPK", "3")),
    "auto_promote": os.getenv("SCHED_PROMOTE", "true").lower() == "true",
}
req = urllib.request.Request(
    BASE.rstrip("/") + "/scheduler/run",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as res:
    print(res.status, res.read().decode())