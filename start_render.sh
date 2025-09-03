#!/usr/bin/env bash
set -euo pipefail

echo "[startup] CWD=$(pwd)"
echo "[startup] Python: $(python --version)"
echo "[startup] sys.path ↓"
python - <<'PY'
import sys, os, importlib
print("\n".join(sys.path))
print("cwd:", os.getcwd())
print("ls:", os.listdir("."))
try:
    importlib.import_module("app.main")
    print("[startup] import app.main OK")
except Exception as e:
    print("[startup] import app.main FAILED:", repr(e))
PY

# 本番起動
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"