<#
.SYNOPSIS
  Run pytest from the project venv. Manual (hardware/desktop) tests are skipped by default (pyproject addopts).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
  powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1 tests\gestures -k clap
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) { Write-Host "No .venv. Run scripts\setup.ps1 first." -ForegroundColor Red; exit 1 }

Push-Location -LiteralPath $Root
try {
    if ($args.Count -gt 0) { & "$Py" -m pytest -q @args } else { & "$Py" -m pytest -q }
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
