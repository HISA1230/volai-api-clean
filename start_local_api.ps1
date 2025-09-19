param(
  [string]$Bind = "127.0.0.1",
  [int]$Port = 8010
)
$ErrorActionPreference = "Stop"
Set-Location "C:\project\volatility_ai"

# 既存プロセス停止（同ポート）
$owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique
if ($owners) {
  foreach ($opid in $owners) {
    try { Stop-Process -Id $opid -Force -ErrorAction SilentlyContinue } catch {}
  }
  Start-Sleep -Milliseconds 300
}

# 必要ENV（ローカル用。※本番はSecretsに）
if (-not $env:ADMIN_TOKEN) { $env:ADMIN_TOKEN = "local-admin-123" }
if (-not $env:SECRET_KEY)  { $env:SECRET_KEY  = "local-secret-CHANGE-ME" }

# 起動（uvicorn→fallbackでpython -m uvicorn）
try {
  uvicorn main_api:app --host $Bind --port $Port --reload
} catch {
  python -m uvicorn main_api:app --host $Bind --port $Port --reload
}
