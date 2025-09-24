## VolAI

![CI](https://github.com/HISA1230/volai-api-clean/actions/workflows/ci.yml/badge.svg)

### Quick Start

```bash
# 1) 仮想環境
python -m venv venv
# Windows PowerShell:
.\venv\Scripts\Activate.ps1

# 2) 依存関係
pip install -r requirements.txt
# (あれば) 開発用
pip install -r requirements-dev.txt

# 3) .env を用意（必要な場合のみ）
# FMP_API_KEY=your_key
# FRED_API_KEY=your_key
# ALIGN_CALENDAR_UNION_FFILL=1