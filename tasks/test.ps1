param([switch]$ci)

# .env が無い／キー未設定でも落ちないように最低限のダミー
if (-not (Test-Path .\.env)) {
@"
FMP_API_KEY=DUMMY
FRED_API_KEY=DUMMY
ALIGN_CALENDAR_UNION_FFILL=1
"@ | Set-Content .\.env -Encoding ascii
}

# 開発用依存関係
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# テスト実行
.\venv\Scripts\python.exe -m pytest -q
