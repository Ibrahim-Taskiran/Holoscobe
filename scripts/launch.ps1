<#
.SYNOPSIS
  Launch Holoscobe from source: python -m handcontrol.app (extra arguments are passed through).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\launch.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) { Write-Host "No .venv. Run scripts\setup.ps1 first." -ForegroundColor Red; exit 1 }
$Model = Join-Path $Root "assets\models\hand_landmarker.task"
if (-not (Test-Path -LiteralPath $Model)) { Write-Host "Model missing. Run scripts\setup.ps1 (or -ModelPath for offline)." -ForegroundColor Red; exit 1 }

$env:PYTHONPATH = (Join-Path $Root "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH
$env:PYTHONUTF8 = "1"
Push-Location -LiteralPath $Root
try {
    & "$Py" -m handcontrol.app @args
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
