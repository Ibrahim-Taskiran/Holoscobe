<# Run the local, input-free click recorder; pass arguments through unchanged. #>
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Proje Python ortamı bulunamadı.' }
$env:PYTHONPATH = (Join-Path $projectRoot 'src') + [IO.Path]::PathSeparator + $env:PYTHONPATH
$env:PYTHONUTF8 = '1'
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m handcontrol.tools.click_record @args
    $exitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $exitCode
