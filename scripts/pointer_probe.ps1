<# Run the opt-in pointer probe; it prompts before moving and never clicks. #>
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Proje Python ortamı bulunamadı.' }
$env:PYTHONPATH = (Join-Path $projectRoot 'src') + [IO.Path]::PathSeparator + $env:PYTHONPATH
$env:PYTHONUTF8 = '1'
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m handcontrol.tools.pointer_probe @args
    $exitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $exitCode
