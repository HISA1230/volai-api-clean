param(
  [string]$Api  = "http://127.0.0.1:8010",
  [int]$Port    = 8501,
  [string]$AutoToken = "",
  [switch]$FindFree,
  [switch]$KillExisting
)
$ErrorActionPreference = "Stop"
Set-Location "C:\project\volatility_ai"

function Test-PortFree([int]$p){
  -not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

$use   = $Port
$owners = Get-NetTCPConnection -LocalPort $use -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique

if ($owners) {
  if ($KillExisting) {
    foreach($opid in $owners){ try { Stop-Process -Id $opid -Force } catch {} }
    Start-Sleep -Milliseconds 300
  } elseif ($FindFree) {
    foreach($p in 8501..8510) { if (Test-PortFree $p) { $use = $p; break } }
  } else {
    Write-Warning "Port $use is busy (PID: $owners). Reusing existing UI at http://localhost:$use"
    Start-Process "http://localhost:$use"
    exit 0
  }
}

$env:API_URL = $Api
if ($AutoToken) { $env:AUTOLOGIN_TOKEN = $AutoToken }

Write-Host "UI starting on http://localhost:$use (API=$Api)"
streamlit run .\streamlit_app.py --server.port $use
