function Db-Where {
  @"
from database.database_user import engine
url = engine.url.render_as_string(hide_password=True)
print("  ok", "url")
print(True, url)
"@ | python -
}

function Use-Local {
  Remove-Item Env:\SQLALCHEMY_DATABASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
  Write-Host "Switched to LOCAL DB (env var removed)"
}

function Use-Neon {
  param([string]$Url)
  if (-not $Url -and $Global:NEON_URL) { $Url = $Global:NEON_URL }
  if (-not $Url) {
    Write-Host "Please pass -Url 'postgresql+psycopg2://...sslmode=require' or set `$Global:NEON_URL"
    return
  }
  $env:SQLALCHEMY_DATABASE_URL = $Url
  $env:DATABASE_URL            = $Url
  Write-Host "Switched to NEON DB"
}
function dl { Use-Local }
function dn { param([string]$Url) if ($PSBoundParameters.ContainsKey('Url')) { Use-Neon -Url $Url } else { Use-Neon } }
function dw { Db-Where }
