<#
.SYNOPSIS
  Build, self-test and zip Holoscobe: dist\Holoscobe-<version>-win64.zip + .sha256.
.PARAMETER SkipBuild
  Reuse the existing dist\Holoscobe folder.
#>
[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $projectRoot 'dist'
$appDir = Join-Path $dist 'Holoscobe'
$exe = Join-Path $appDir 'Holoscobe.exe'

$m = Select-String -LiteralPath (Join-Path $projectRoot 'pyproject.toml') -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { throw 'version not found in pyproject.toml' }
$version = $m.Matches[0].Groups[1].Value

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'build.ps1')
}
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Missing $exe. Run scripts\build.ps1 first." }

# Self-test: no window, no camera. The exe is windowed, so it writes its result to a file.
$report = Join-Path ([IO.Path]::GetTempPath()) "holoscobe_selftest_$PID.txt"
Remove-Item -LiteralPath $report -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath $exe -ArgumentList '--self-test', "`"$report`"" -Wait -PassThru
$line = if (Test-Path -LiteralPath $report) { (Get-Content -LiteralPath $report -TotalCount 1) } else { '(no report)' }
Write-Output "Self-test: $line"
if ($proc.ExitCode -ne 0 -or $line -notlike 'OK*') { throw "Self-test failed (exit $($proc.ExitCode))." }

$zip = Join-Path $dist "Holoscobe-$version-win64.zip"
Remove-Item -LiteralPath $zip, "$zip.sha256" -ErrorAction SilentlyContinue
# bsdtar (Windows 10+) writes forward-slash zip entries; Compress-Archive in PS 5.1 does not.
& tar.exe -a -c -f $zip -C $dist 'Holoscobe'
if ($LASTEXITCODE -ne 0) { throw "tar failed with exit code $LASTEXITCODE" }

$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$zip.sha256", "$hash  $(Split-Path -Leaf $zip)`n", (New-Object Text.UTF8Encoding($false)))
Write-Output "Release: $zip"
Write-Output "SHA-256: $hash"
