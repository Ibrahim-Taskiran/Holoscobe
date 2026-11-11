<#
.SYNOPSIS
  Holoscobe setup: Python 3.11 venv + locked packages + verified hand landmarker model.
.DESCRIPTION
  1. Creates .venv with Python 3.11 x64 (uv if present, else the py launcher).
  2. Installs exact, hash-checked packages from requirements.lock.
  3. Obtains assets/models/hand_landmarker.task from the official URL in assets/model_manifest.json
     (or copies it from -ModelPath for an offline machine) and verifies SHA-256 against the manifest.
     Any mismatch stops the script with an error; a mismatching file is never kept.
  Works from paths containing spaces and non-ASCII (e.g. Turkish) characters.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -ModelPath "D:\offline\hand_landmarker.task"
#>
[CmdletBinding()]
param(
    [string]$ModelPath = "",   # offline: use this local copy instead of downloading
    [switch]$SkipPackages,
    [switch]$SkipModel
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Lock = Join-Path $Root "requirements.lock"
$Manifest = Join-Path $Root "assets\model_manifest.json"

function Fail([string]$msg) { Write-Host "SETUP FAILED: $msg" -ForegroundColor Red; exit 1 }
function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Have([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# PySide6 files sit up to ~151 chars below .venv\Lib\site-packages; deep roots pass MAX_PATH (260).
$lp = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
if ($Root.Length -gt 80 -and $lp -ne 1) {
    Write-Host "WARNING: project path is $($Root.Length) chars and Windows long paths are off; some .venv files may exceed 260 chars." -ForegroundColor Yellow
    Write-Host "         Use a shorter folder (e.g. C:\Holoscobe) or enable LongPathsEnabled (admin)." -ForegroundColor Yellow
}

# ---------- 1. venv ----------
if (-not $SkipPackages) {
    $uv = Have "uv"
    if (-not (Test-Path -LiteralPath $Py)) {
        Step "Creating venv (Python 3.11) at $Venv"
        if ($uv) { & uv venv --python 3.11 "$Venv" }
        elseif (Have "py") { & py -3.11 -m venv "$Venv" }
        else { Fail "Python 3.11 not found. Install it free from python.org (64-bit) or install uv, then re-run." }
        if ($LASTEXITCODE -ne 0) { Fail "venv creation failed (exit $LASTEXITCODE)" }
    }
    $ver = & "$Py" -c "import sys,platform;print('%d.%d|%s' % (sys.version_info[0], sys.version_info[1], platform.machine()))"
    if ($ver -ne "3.11|AMD64") { Fail "venv must be Python 3.11 x64, got '$ver'. Delete .venv and re-run." }

    # ---------- 2. packages ----------
    Step "Installing locked packages (hash-checked) from requirements.lock"
    if ($uv) { & uv pip install --python "$Py" --require-hashes -r "$Lock" }
    else {
        & "$Py" -m pip install --upgrade pip
        & "$Py" -m pip install --require-hashes --no-deps -r "$Lock"
    }
    if ($LASTEXITCODE -ne 0) { Fail "package install failed (exit $LASTEXITCODE)" }
    & "$Py" -c "import mediapipe, cv2, PySide6.QtWidgets, pycaw, comtypes; print('imports OK')"
    if ($LASTEXITCODE -ne 0) { Fail "import check failed" }
}

# ---------- 3. model ----------
if (-not $SkipModel) {
    $m = (Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json).models[0]
    $dest = Join-Path $Root ($m.local_path -replace "/", "\")
    $expected = $m.sha256.ToLowerInvariant()
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null

    function HashOf([string]$p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }

    if ((Test-Path -LiteralPath $dest) -and ((HashOf $dest) -eq $expected)) {
        Step "Model already present and verified: $dest"
    } else {
        $tmp = "$dest.partial"
        if ($ModelPath) {
            Step "Copying model from $ModelPath (offline)"
            Copy-Item -LiteralPath $ModelPath -Destination $tmp -Force
        } else {
            Step "Downloading model: $($m.url)"
            try { Invoke-WebRequest -UseBasicParsing -Uri $m.url -OutFile $tmp }
            catch { Fail "model download failed: $($_.Exception.Message). Offline? Use -ModelPath." }
        }
        $actual = HashOf $tmp
        if ($actual -ne $expected) {
            Remove-Item -LiteralPath $tmp -Force
            Fail "MODEL SHA-256 MISMATCH. expected $expected, got $actual. File deleted; do not use it."
        }
        Move-Item -LiteralPath $tmp -Destination $dest -Force
        Step "Model verified (SHA-256 $expected)"
    }
    Write-Host "    hash status: $($m.sha256_status)" -ForegroundColor Yellow
    Write-Host "    license: $($m.license) | $($m.redistribution_status)"
}

Step "Setup complete. Tests: scripts\run_tests.ps1   Launch: scripts\launch.ps1"
exit 0
