# ===== Volai tools (ASCII only; works on WinPS 5.1 & PS7) =====
$global:base = 'https://volai-api-02.onrender.com'
[System.Net.ServicePointManager]::Expect100Continue = $false
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 } catch {}

function Set-VolaiBase {
  param([Parameter(Mandatory=$true)][string]$Url)
  try { [void][uri]$Url } catch { throw "Invalid URL: $Url" }
  $global:base = $Url.TrimEnd('/')
}
function Show-VolaiBase { "BASE = $global:base" }

# --- helpers ---
function _SanitizeName {
  param([string]$s)
  if (-not $s) { return $s }
  $invalid = [IO.Path]::GetInvalidFileNameChars()
  foreach ($ch in $invalid) { $s = $s -replace [regex]::Escape([string]$ch), '_' }
  return $s
}

function Get-Token {
  [CmdletBinding()]
  param(
    [string]$Email='test@example.com',
    [string]$Password='test1234',
    [int]$TimeoutSec=45,
    [int]$Retries=2
  )
  $body = @{ email=$Email; password=$Password } | ConvertTo-Json
  for ($i=0; $i -le $Retries; $i++) {
    try {
      $resp = Invoke-RestMethod -Method POST -Uri "$global:base/login" `
        -Headers @{ 'Content-Type'='application/json'; 'Expect'='' } `
        -Body $body -TimeoutSec $TimeoutSec -DisableKeepAlive -ErrorAction Stop
      if ($resp.access_token) { return $resp.access_token }
      throw "No access_token in response."
    } catch {
      if ($i -lt $Retries) { Start-Sleep -Seconds (2 + 2*$i); continue }
      throw ("Get-Token failed after {0} tries: {1}" -f ($Retries+1), $_.Exception.Message)
    }
  }
}

function Me {
  param([Parameter(Mandatory=$true)][string]$Token, [int]$TimeoutSec=20)
  Invoke-RestMethod -Uri "$global:base/me" `
    -Headers @{ Authorization = "Bearer $Token"; 'Accept'='application/json' } `
    -TimeoutSec $TimeoutSec -DisableKeepAlive -ErrorAction Stop
}

function Summary {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$Start = '',
    [string]$End = '',
    [string]$TimeStart = '',
    [string]$TimeEnd = '',
    [int]$TzOffset = 0,
    [switch]$AsJson,
    [int]$TimeoutSec = 60,
    [int]$Retries = 2
  )
  $qs = @("by=$By")
  if ($Owner)     { $qs += "owner=$([uri]::EscapeDataString($Owner))" }
  if ($Start)     { $qs += "start=$Start" }
  if ($End)       { $qs += "end=$End" }
  if ($TimeStart) { $qs += "time_start=$TimeStart" }
  if ($TimeEnd)   { $qs += "time_end=$TimeEnd" }
  if ($TzOffset -ne 0) { $qs += "tz_offset=$TzOffset" }
  $url = "$global:base/predict/logs/summary?$(($qs -join '&'))"
  if ($PSBoundParameters.ContainsKey('Verbose')) { Write-Verbose "GET $url" }

  for ($i=0; $i -le $Retries; $i++) {
    try {
      $resp = Invoke-WebRequest -Uri $url -TimeoutSec $TimeoutSec `
        -Headers @{ 'Accept'='application/json'; 'Expect'='' } `
        -DisableKeepAlive -ErrorAction Stop
      if ($AsJson) { return ($resp.Content | ConvertFrom-Json) }
      else         { return $resp.Content }
    } catch {
      if ($i -lt $Retries) { Start-Sleep -Seconds (3 + 2*$i); continue }
      throw ("Summary failed after {0} tries: {1}`nURL: {2}" -f ($Retries+1), $_.Exception.Message, $url)
    }
  }
}

function SummaryJST {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$Start = '',
    [string]$End = '',
    [string]$TimeStart = '',
    [string]$TimeEnd = '',
    [switch]$AsJson,
    [int]$TimeoutSec = 60,
    [int]$Retries = 2
  )
  Summary -By $By -Owner $Owner -Start $Start -End $End `
    -TimeStart $TimeStart -TimeEnd $TimeEnd -TzOffset 540 `
    -AsJson:$AsJson -TimeoutSec $TimeoutSec -Retries $Retries
}

function Save-VolaiSummary {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$Start = '',
    [string]$End   = '',
    [string]$TimeStart = '09:30',
    [string]$TimeEnd   = '12:00',
    [switch]$Yesterday,
    [switch]$Last7Days,
    [switch]$LastWeek,
    [string]$Path,
    [switch]$Xlsx,
    [string]$SheetName = 'Summary',
    [int]$TimeoutSec = 60,
    [int]$Retries = 2,
    [switch]$OpenAfter
  )

  # decide period
  if ($Yesterday) {
    $Start = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd'); $End = $Start
  } elseif ($Last7Days) {
    $End = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
    $Start = (Get-Date).AddDays(-7).ToString('yyyy-MM-dd')
  } elseif ($LastWeek) {
    $today = Get-Date
    $d = (([int]$today.DayOfWeek + 6) % 7)
    $thisMon = $today.Date.AddDays(-$d)
    $Start = $thisMon.AddDays(-7).ToString('yyyy-MM-dd')
    $End   = $thisMon.AddDays(-1).ToString('yyyy-MM-dd')
  }
  if (-not $Start -or -not $End) {
    throw "Please specify period by -Start/-End or -Yesterday/-Last7Days/-LastWeek."
  }

  # fetch data
  $data = SummaryJST -By $By -Owner $Owner -Start $Start -End $End `
           -TimeStart $TimeStart -TimeEnd $TimeEnd -AsJson `
           -TimeoutSec $TimeoutSec -Retries $Retries -Verbose:$false

  # file path
  $ownerSafe = if ($Owner) { _SanitizeName $Owner } else { '(all)' }
  $periodTag = "${Start}_${End}"
  $tband = $TimeStart.Replace(':','') + '-' + $TimeEnd.Replace(':','')
  if (-not $Path) {
    $base = "volai-$By-$ownerSafe-$periodTag-$tband"
    $Path = Join-Path (Get-Location) ($base + ($(if($Xlsx){'.xlsx'} else {'.csv'})))
  } else {
    if ($Xlsx -and -not ($Path.ToLower().EndsWith('.xlsx'))) { $Path += '.xlsx' }
    if (-not $Xlsx -and -not ($Path.ToLower().EndsWith('.csv'))) { $Path += '.csv' }
  }
  $dir = Split-Path -Parent $Path
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

  # save
  $saved = $null
  if ($Xlsx) {
    $hasImportExcel = @(Get-Module -ListAvailable -Name ImportExcel).Count -gt 0
    if ($hasImportExcel) {
      try {
        $data | Export-Excel -Path $Path -WorksheetName $SheetName `
          -AutoSize -BoldTopRow -FreezeTopRow -AutoFilter -ClearSheet
        $saved = 'xlsx'
      } catch {
        $baseName = [IO.Path]::GetFileNameWithoutExtension($Path)
        $altName  = ("{0}-alt_{1:HHmmss}.xlsx" -f $baseName, (Get-Date))
        $alt      = [IO.Path]::Combine($dir, $altName)
        $data | Export-Excel -Path $alt -WorksheetName $SheetName `
          -AutoSize -BoldTopRow -FreezeTopRow -AutoFilter -ClearSheet
        $Path = $alt; $saved = 'xlsx'
      }
    } else {
      $prog = [type]::GetTypeFromProgID('Excel.Application')
      if ($prog) {
        $xl = $wb = $ws = $null
        try {
          $xl = New-Object -ComObject Excel.Application
          $wb = $xl.Workbooks.Add(); $ws = $wb.Worksheets.Item(1)
          $ws.Cells.Item(1,1) = 'key'; $ws.Cells.Item(1,2) = 'count'
          $r = 2; foreach ($row in $data) { $ws.Cells.Item($r,1) = $row.key; $ws.Cells.Item($r,2) = $row.count; $r++ }
          $wb.SaveAs($Path); $saved = 'xlsx'
        } finally {
          if ($wb) { $wb.Close($true) }
          if ($xl) { $xl.Quit(); [Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null }
        }
      }
    }
  }
  if (-not $saved) {
    if (-not ($Path.ToLower().EndsWith('.csv'))) { $Path += '.csv' }
    $data | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $Path
    $saved = 'csv'
  }

  Write-Host "Saved ($saved): $Path"
  if ($OpenAfter) { Start-Process $Path | Out-Null }
  return $Path
}

function Refresh-OpenAPI {
  param([Parameter(Mandatory=$true)][string]$AdminToken)
  Invoke-RestMethod -Method POST -Uri "$global:base/ops/openapi/refresh" `
    -Headers @{ 'X-Admin-Token' = $AdminToken } -TimeoutSec 30 -ErrorAction Stop | Out-Null
  Invoke-RestMethod -Uri "$global:base/openapi.json?v=$([int](Get-Date -UFormat %s))" `
    -TimeoutSec 30 -ErrorAction Stop | Out-Null
}

function Ping-Volai {
  param([int]$TimeoutSec = 12)
  try {
    $r = Invoke-RestMethod -Uri "$global:base/" -TimeoutSec $TimeoutSec -ErrorAction Stop
    [pscustomobject]@{ ok=[bool]$r.ok; version=$r.version; time_utc=$r.time_utc; source="/" }
  } catch {
    try {
      $w = Invoke-WebRequest -Uri "$global:base/health" -TimeoutSec $TimeoutSec `
            -Headers @{ 'Expect' = '' } -DisableKeepAlive -ErrorAction Stop
      [pscustomobject]@{ ok=($w.StatusCode -eq 200); version=$null; time_utc=$null; source="/health" }
    } catch {
      [pscustomobject]@{ ok=$false; version=$null; time_utc=$null; source="error"; error=$_.Exception.Message }
    }
  }
}
function Health {
  param([int]$TimeoutSec = 12)
  $p = Ping-Volai -TimeoutSec $TimeoutSec
  if ($p.ok) { 200 } else { throw "Health failed via $($p.source): $($p.error)" }
}

function Volai-SmokeTest {
  try {
    $ping = Ping-Volai
    "Ping:    ok=$($ping.ok) source=$($ping.source) version=$($ping.version)"
    "Health:  $(Health)"
    $tok = Get-Token -TimeoutSec 60 -Retries 3
    $me  = Me -Token $tok
    "Me:     $($me.email)"
    $ownerCommon = [uri]::UnescapeDataString('%E5%85%B1%E7%94%A8')  # "shared"
    $msg = "Summary (JST 09:30-12:00; owner=$ownerCommon; 2025-08-01..31)"
    $msg
    SummaryJST -By size -Owner $ownerCommon -Start 2025-08-01 -End 2025-08-31 `
      -TimeStart '09:30' -TimeEnd '12:00' -AsJson | Format-Table -AutoSize
  } catch {
    Write-Error $_
  }
}

function SummaryTodayJST {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$TimeStart = '09:30',
    [string]$TimeEnd = '12:00',
    [switch]$AsJson
  )
  $today = (Get-Date -Format yyyy-MM-dd)
  SummaryJST -By $By -Owner $Owner -Start $today -End $today `
    -TimeStart $TimeStart -TimeEnd $TimeEnd -AsJson:$AsJson
}

# ===== shortcuts =====
function SummaryYesterdayJST {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$TimeStart = '09:30',
    [string]$TimeEnd   = '12:00',
    [switch]$AsJson
  )
  $d = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
  SummaryJST -By $By -Owner $Owner -Start $d -End $d -TimeStart $TimeStart -TimeEnd $TimeEnd -AsJson:$AsJson
}

function SummaryLast7DaysJST {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$TimeStart = '09:30',
    [string]$TimeEnd   = '12:00',
    [switch]$AsJson
  )
  $end   = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
  $start = (Get-Date).AddDays(-7).ToString('yyyy-MM-dd')
  SummaryJST -By $By -Owner $Owner -Start $start -End $end -TimeStart $TimeStart -TimeEnd $TimeEnd -AsJson:$AsJson
}

function SummaryLastWeekJST {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [string]$TimeStart = '09:30',
    [string]$TimeEnd   = '12:00',
    [switch]$AsJson
  )
  $today = Get-Date
  $daysSinceMon = (([int]$today.DayOfWeek + 6) % 7)
  $thisMon = $today.Date.AddDays(-$daysSinceMon)
  $lastMon = $thisMon.AddDays(-7)
  $lastSun = $thisMon.AddDays(-1)
  $start = $lastMon.ToString('yyyy-MM-dd')
  $end   = $lastSun.ToString('yyyy-MM-dd')
  SummaryJST -By $By -Owner $Owner -Start $start -End $end -TimeStart $TimeStart -TimeEnd $TimeEnd -AsJson:$AsJson
}

# ===== add-ons: charts & multi-sheets =====
function Save-VolaiSummaryWithChart {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'owner',
    [string]$Owner = '',
    [Parameter(Mandatory=$true)][string]$Start,
    [Parameter(Mandatory=$true)][string]$End,
    [string]$TimeStart = '09:30',
    [string]$TimeEnd   = '12:00',
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$SheetName = 'Summary',
    [switch]$OpenAfter
  )
  $data = SummaryJST -By $By -Owner $Owner -Start $Start -End $End -TimeStart $TimeStart -TimeEnd $TimeEnd -AsJson
  $hasImportExcel = @(Get-Module -ListAvailable -Name ImportExcel).Count -gt 0
  if ($hasImportExcel) {
    if (-not ($Path.ToLower().EndsWith('.xlsx'))) { $Path += '.xlsx' }
    $rows = ($data | Measure-Object).Count + 1
    $xRange = "A2:A$rows"
    $yRange = "B2:B$rows"
    $title  = "by=$By; owner=$Owner; $Start..$End; $TimeStart-$TimeEnd"
    $chart = New-ExcelChartDefinition -ChartType ColumnClustered -Title $title -XRange $xRange -YRange $yRange
    $pkg = $data | Export-Excel -Path $Path -WorksheetName $SheetName `
            -AutoSize -BoldTopRow -FreezeTopRow -AutoFilter -ClearSheet `
            -ExcelChartDefinition $chart -PassThru
    Close-ExcelPackage $pkg
  } else {
    Save-VolaiSummary -By $By -Owner $Owner -Start $Start -End $End -TimeStart $TimeStart -TimeEnd $TimeEnd -Path $Path -Xlsx:$true | Out-Null
  }
  if ($OpenAfter) { Start-Process $Path }
  return $Path
}

function Save-VolaiDailyTwoSlots {
  param(
    [ValidateSet('owner','sector','size')] [string]$By = 'size',
    [string]$Owner = '',
    [datetime]$Date = (Get-Date).AddDays(-1),
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$MorningStart = '09:30',
    [string]$MorningEnd   = '12:00',
    [string]$NightStart   = '00:30',
    [string]$NightEnd     = '03:00',
    [switch]$OpenAfter
  )
  $d = $Date.ToString('yyyy-MM-dd')
  $m1 = $MorningStart.Replace(':',''); $m2 = $MorningEnd.Replace(':','')
  $n1 = $NightStart.Replace(':','');   $n2 = $NightEnd.Replace(':','')
  $sheet1 = "$d $m1-$m2"
  $sheet2 = "$d $n1-$n2"
  Save-VolaiSummaryWithChart -By $By -Owner $Owner -Start $d -End $d -TimeStart $MorningStart -TimeEnd $MorningEnd -Path $Path -SheetName $sheet1 | Out-Null
  Save-VolaiSummaryWithChart -By $By -Owner $Owner -Start $d -End $d -TimeStart $NightStart -TimeEnd $NightEnd -Path $Path -SheetName $sheet2 | Out-Null
  if ($OpenAfter) { Start-Process $Path }
  return $Path
}

function Save-VolaiAllAxesYesterday {
  param(
    [string]$Owner = '',
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$TimeStart = '09:30',
    [string]$TimeEnd   = '12:00',
    [switch]$OpenAfter
  )
  $d = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
  $tb = $TimeStart.Replace(':','') + '-' + $TimeEnd.Replace(':','')
  foreach ($by in 'size','sector','owner') {
    $sheet = "$d $by $tb"
    Save-VolaiSummaryWithChart -By $by -Owner $Owner -Start $d -End $d -TimeStart $TimeStart -TimeEnd $TimeEnd -Path $Path -SheetName $sheet | Out-Null
  }
  if ($OpenAfter) { Start-Process $Path }
  return $Path
}
# ===== /Volai add-ons =====