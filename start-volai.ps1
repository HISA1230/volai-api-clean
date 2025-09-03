param(
  [int]$Port = 8011,                        # ← 8011 をデフォルトに
  [string]$DbUrl = $env:DATABASE_URL,       # 引数優先、なければ既存環境変数
  [switch]$Reload                           # ホットリロード
)

# 1) ポートのリスナーを掃除（同ポート競合の回避）
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue `
| Select-Object -ExpandProperty OwningProcess -Unique `
| ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

# 2) 環境変数の用意
$env:PYTHONPATH = (Get-Location).Path
if ($DbUrl) { 
  $env:DATABASE_URL = $DbUrl 
} elseif (-not $env:DATABASE_URL) {
  # secrets ファイルがあれば読み込む（例: ここで $env:DATABASE_URL を設定）
  if (Test-Path .\start-volai.secrets.ps1) { . .\start-volai.secrets.ps1 }
}

if (-not $env:DATABASE_URL) {
  Write-Error "DATABASE_URL is not set. -DbUrl で渡すか、環境変数/ secrets を設定してください。"
  exit 1
}

# 3) Uvicorn 引数
$uvArgs = @("app.main:app","--host","127.0.0.1","--port",$Port,"--workers","1")
if ($Reload) { $uvArgs += "--reload" }

Write-Host "Starting VolAI on http://127.0.0.1:$Port  (workers=1, reload=$Reload)"
& uvicorn @uvArgs