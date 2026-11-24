<#
.SYNOPSIS
  Point the single desktop shortcut "Holoscobe" at the current source (real control, no console window).
.DESCRIPTION
  The source launcher never goes stale: no rebuild is needed after a code change. An older
  "Holoscobe - Canli" shortcut is removed.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'scripts\holoscobe.pyw'
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $pythonw)) {
    throw 'Holoscobe launcher or virtual environment is missing.'
}
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop 'Holoscobe.lnk'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $launcher + '" --live'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Holoscobe'
$shortcut.WindowStyle = 1
# Windows caches icons by path, so every new icon gets its own file name.
$icon = Join-Path $root 'assets\icon.ico'
$iconDir = Join-Path $env:LOCALAPPDATA 'Holoscobe\icons'
$copy = Join-Path $iconDir ('icon-' + (Get-FileHash -LiteralPath $icon).Hash.Substring(0, 8) + '.ico')
New-Item -ItemType Directory -Force -Path $iconDir | Out-Null
Copy-Item -LiteralPath $icon -Destination $copy -Force
$shortcut.IconLocation = $copy + ',0'
$shortcut.Save()
$old = Join-Path $desktop 'Holoscobe - Canli.lnk'
if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old }
Write-Output "$path -> $($shortcut.TargetPath) $($shortcut.Arguments)"
