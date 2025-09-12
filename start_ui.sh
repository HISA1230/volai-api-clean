#!/usr/bin/env bash
set -euo pipefail

# env ? API_BASE ????????????
: "${API_BASE:=https://volai-api-prod.onrender.com}"

# Streamlit ??
exec python -m streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port "$PORT"