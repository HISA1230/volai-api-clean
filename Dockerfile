# UI 用
FROM python:3.11-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 依存（ca-certificates も入れる）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements-ui.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements-ui.txt

# アプリ本体
COPY streamlit_app.py .

EXPOSE 8502

# ← バックスラッシュ連結だと空行で壊れやすいので、ENV を分割（安全）
ENV STREAMLIT_SERVER_PORT=${PORT:-8502}
ENV STREAMLIT_SERVER_ENABLECORS=false
ENV STREAMLIT_SERVER_ENABLEXsrfProtection=false
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# PORT が来たらそれを使い、無ければ 8502
CMD ["bash","-lc","streamlit run streamlit_app.py --server.port=${PORT:-8502} --server.address=0.0.0.0"]