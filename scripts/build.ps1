<#
.SYNOPSIS
  Verify model hashes and build a windowed one-folder Holoscobe using the local venv.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
# CI sets HOLOSCOBE_PYTHON to its interpreter; locally the project .venv is used.
$pythonPath = if ($env:HOLOSCOBE_PYTHON) { (Get-Command $env:HOLOSCOBE_PYTHON).Source } else { Join-Path $projectRoot '.venv\Scripts\python.exe' }
$manifestPath = Join-Path $projectRoot 'assets\model_manifest.json'
$specPath = Join-Path $projectRoot 'packaging\holoscobe.spec'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'The project .venv Python is missing. No packages will be installed.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $manifest.models -or $manifest.models.Count -eq 0) { throw 'No models in manifest.' }
foreach ($model in $manifest.models) {
    if ($model.sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw "Invalid model hash: $($model.id)" }
    $modelPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $model.local_path))
    $assetsPrefix = (Join-Path $projectRoot 'assets') + [IO.Path]::DirectorySeparatorChar
    if (-not $modelPath.StartsWith($assetsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Model path must stay inside assets: $($model.id)"
    }
    $actualHash = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash
    if ($actualHash -ine $model.sha256) { throw "Model SHA-256 mismatch: $($model.id)" }
    Write-Output "Verified model SHA-256: $($model.id)"
}

$oldBytecode = $env:PYTHONDONTWRITEBYTECODE
$oldCache = $env:PYINSTALLER_CONFIG_DIR
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot 'build\.pyinstaller-cache'
$buildTimer = [Diagnostics.Stopwatch]::StartNew()
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -B -c "import PyInstaller; assert PyInstaller.__version__ == '6.22.3', 'PyInstaller 6.22.3 is required'"
    if ($LASTEXITCODE -ne 0) { throw 'The pinned PyInstaller is unavailable. No packages will be installed.' }
    # PyInstaller logs to stderr; do not let PowerShell turn that into a terminating error.
    $ErrorActionPreference = 'Continue'
    & $pythonPath -B -m PyInstaller --noconfirm --distpath (Join-Path $projectRoot 'dist') --workpath (Join-Path $projectRoot 'build') $specPath
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    $exePath = Join-Path $projectRoot 'dist\Holoscobe\Holoscobe.exe'
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw 'Expected executable was not produced.' }
    $bundleBytes = (Get-ChildItem -LiteralPath (Split-Path -Parent $exePath) -Recurse -File | Measure-Object -Property Length -Sum).Sum
    Write-Output "Build complete: $exePath"
    Write-Output "Bundle bytes: $bundleBytes; elapsed seconds: $([math]::Round($buildTimer.Elapsed.TotalSeconds, 2))"
} finally {
    Pop-Location
    $env:PYTHONDONTWRITEBYTECODE = $oldBytecode
    $env:PYINSTALLER_CONFIG_DIR = $oldCache
}
