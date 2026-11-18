<#
.SYNOPSIS
  Per-user install (no admin): copy the onedir build to %LOCALAPPDATA%\Programs\Holoscobe and add a Start Menu shortcut.
.PARAMETER Source
  Folder holding Holoscobe.exe. Default: this script's folder, else ..\dist\Holoscobe.
.PARAMETER Desktop
  Also create a Desktop shortcut.
.PARAMETER DryRun
  Only print the actions.
#>
[CmdletBinding()]
param([string]$Source, [switch]$Desktop, [switch]$DryRun)

$ErrorActionPreference = 'Stop'
if (-not $Source) {
    $candidates = @($PSScriptRoot, (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\Holoscobe'))
    $Source = $candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'Holoscobe.exe') } | Select-Object -First 1
}
if (-not $Source -or -not (Test-Path -LiteralPath (Join-Path $Source 'Holoscobe.exe'))) { throw 'Holoscobe.exe not found. Pass -Source <folder>.' }
$Source = (Resolve-Path -LiteralPath $Source).Path

$target = Join-Path $env:LOCALAPPDATA 'Programs\Holoscobe'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Holoscobe.lnk'
$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Holoscobe.lnk'

function Do-Step([string]$text, [scriptblock]$action) {
    if ($DryRun) { Write-Output "[DryRun] $text" } else { Write-Output $text; & $action }
}
function New-Shortcut([string]$path) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = Join-Path $target 'Holoscobe.exe'
    $s.WorkingDirectory = $target
    $s.Save()
}

if ($Source.TrimEnd('\') -ieq $target.TrimEnd('\')) { throw 'Source and target are the same folder.' }
Do-Step "Copy $Source -> $target" {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item -Path (Join-Path $Source '*') -Destination $target -Recurse -Force
}
Do-Step "Create shortcut $startMenu" { New-Shortcut $startMenu }
if ($Desktop) { Do-Step "Create shortcut $desktopLnk" { New-Shortcut $desktopLnk } }
Write-Output 'Done. Auto-start is configured from inside the app.'
