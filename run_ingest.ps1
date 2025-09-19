# C:\project\volatility_ai\run_ingest.ps1

param(
  [switch]$ForceBadDb = $false   # ← これを付けて実行すると、DBを「わざと失敗」にします
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
Set-Location "C:\project\volatility_ai"

# --- helper: Userスコープ → プロセス環境へ確実に載せる（Env→User→Registry 順） ---
function Get-UserEnvReg([string]$name) {
  try { (Get-ItemProperty -Path 'HKCU:\Environment' -Name $name -ErrorAction Stop).$name } catch { $null }
}
function Import-Env([string[]]$names) {
  foreach ($k in $names) {
    $cur = ${env:$k}
    if ([string]::IsNullOrEmpty($cur)) {
      $u = [Environment]::GetEnvironmentVariable($k, 'User')
      if ([string]::IsNullOrEmpty($u)) { $u = Get-UserEnvReg $k }
      if (-not [string]::IsNullOrEmpty($u)) {
        [Environment]::SetEnvironmentVariable($k, $u, 'Process')
      }
    }
  }
}

# --- Env 取り込み（DB/API 系・SMTP 系） ---
Import-Env @('FMP_API_KEY','FRED_API_KEY','DATABASE_URL','USE_FRED_ONLY')
Import-Env @('SMTP_USER','SMTP_FROM','SMTP_TO','SMTP_HOST','SMTP_PORT','SMTP_TLS','SMTP_PASS')

# SMTP の簡易フォールバック（FROM/TO 未設定なら USER を使う）
if (-not ${env:SMTP_FROM} -and ${env:SMTP_USER}) { ${env:SMTP_FROM} = ${env:SMTP_USER} }
if (-not ${env:SMTP_TO}   -and ${env:SMTP_USER}) { ${env:SMTP_TO}   = ${env:SMTP_USER} }

# DB URL 正規化
if ($env:DATABASE_URL) {
  $env:DATABASE_URL = $env:DATABASE_URL -replace '^postgresql\+psycopg2://','postgresql://'
}

# ← テスト用：ここで「わざと」DBを壊すと、必ず失敗→通知メールが飛びます
if ($ForceBadDb) {
  Write-Host "TEST: Forcing bad DATABASE_URL for failure path..."
  $env:DATABASE_URL = 'postgresql://bad'
}

# --- 失敗メール送信 ---
function Send-IngestFailureMail {
  param([string]$subject, [string]$body)
  try {
    Import-Env @('SMTP_USER','SMTP_FROM','SMTP_TO','SMTP_HOST','SMTP_PORT','SMTP_TLS','SMTP_PASS')
    if ([string]::IsNullOrEmpty($env:SMTP_FROM) -and $env:SMTP_USER) { $env:SMTP_FROM = $env:SMTP_USER }
    if ([string]::IsNullOrEmpty($env:SMTP_TO)   -and $env:SMTP_USER) { $env:SMTP_TO   = $env:SMTP_USER }

    $passLen = ($(if ($env:SMTP_PASS) { $env:SMTP_PASS.Length } else { 0 }))
    Write-Host ("SMTP_USER={0} FROM={1} TO={2} HOST={3} PORT={4} TLS={5} PASS_len={6}" -f `
      $env:SMTP_USER, $env:SMTP_FROM, $env:SMTP_TO, $env:SMTP_HOST, $env:SMTP_PORT, $env:SMTP_TLS, $passLen)

    if ([string]::IsNullOrEmpty($env:SMTP_USER) -or
        [string]::IsNullOrEmpty($env:SMTP_HOST) -or
        [string]::IsNullOrEmpty($env:SMTP_PASS)) {
      Write-Warning "SMTP設定が不完全のため通知メールをスキップします。USER/HOST/PASS を確認してください。"
      return
    }

    $fromAddr = New-Object System.Net.Mail.MailAddress($env:SMTP_FROM)
    $toAddr   = New-Object System.Net.Mail.MailAddress($env:SMTP_TO)

    $msg = New-Object System.Net.Mail.MailMessage
    $msg.From = $fromAddr
    $msg.To.Add($toAddr)
    $msg.Subject = $subject
    $msg.Body    = $body
    $msg.SubjectEncoding = [System.Text.Encoding]::UTF8
    $msg.BodyEncoding    = [System.Text.Encoding]::UTF8
    $msg.IsBodyHtml = $false

    $smtp = New-Object System.Net.Mail.SmtpClient($env:SMTP_HOST, [int]$env:SMTP_PORT)
    if ($env:SMTP_TLS -eq '1') { $smtp.EnableSsl = $true }
    $smtp.Credentials = New-Object System.Net.NetworkCredential($env:SMTP_USER, $env:SMTP_PASS)

    $smtp.Send($msg)
    Write-Host "通知メール送信: $subject"
  } catch {
    Write-Warning ("通知メール送信に失敗: " + $_.Exception.Message)
  }
}

function TailText($path) {
  if (Test-Path $path) { (Get-Content $path -Tail 120 | Out-String) } else { "log not found: $path" }
}

# --- ログ準備 ---
if (-not (Test-Path .\logs)) { New-Item -ItemType Directory -Path .\logs | Out-Null }
$stamp      = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$python     = "C:\project\volatility_ai\venv\Scripts\python.exe"
$ingestLog  = ".\logs\ingest_$stamp.log"
$countsLog  = ".\logs\counts_$stamp.log"

# --- 実行（失敗時だけメール） ---
cmd /c ""$python" .\scripts\ingest_macro.py >> "$ingestLog" 2>&1"
$ingestExit = $LASTEXITCODE
Write-Host "ingest exit: $ingestExit  log: $ingestLog"
if ($ingestExit -ne 0) {
  $body = "ingest_macro.py が失敗しました (exit=$ingestExit)`r`n--- last log ---`r`n$(TailText $ingestLog)"
  Send-IngestFailureMail -subject "[VolAI] Ingest failed ($stamp)" -body $body
  exit $ingestExit
}

cmd /c ""$python" .\check_counts.py >> "$countsLog" 2>&1"
$countsExit = $LASTEXITCODE
Write-Host "counts exit: $countsExit  log: $countsLog"
if ($countsExit -ne 0) {
  $body = "check_counts.py が失敗しました (exit=$countsExit)`r`n--- last log ---`r`n$(TailText $countsLog)"
  Send-IngestFailureMail -subject "[VolAI] Counts failed ($stamp)" -body $body
}

exit $countsExit