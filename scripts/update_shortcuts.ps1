<#
.SYNOPSIS
  Refresh desktop shortcuts to launch the current source checkout with live control and telemetry.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$shortcutRoot = Split-Path -Parent $PSScriptRoot
$shortcutLauncher = Join-Path $shortcutRoot 'scripts\launch.ps1'
$shortcutPython = Join-Path $shortcutRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $shortcutLauncher) -or -not (Test-Path -LiteralPath $shortcutPython)) {
    throw 'Holoscobe launcher or virtual environment is missing.'
}
$shortcutDesktop = [Environment]::GetFolderPath('Desktop')
$shortcutShell = New-Object -ComObject WScript.Shell
foreach ($shortcutName in @('Holoscobe.lnk', 'Holoscobe - Canli.lnk')) {
    $shortcutPath = Join-Path $shortcutDesktop $shortcutName
    $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $shortcutLauncher + '" --live --telemetry'
    $shortcut.WorkingDirectory = $shortcutRoot
    $shortcut.Description = 'Holoscobe - Gercek fare kontrolu ve telemetri'
    $shortcut.WindowStyle = 7
    $shortcut.IconLocation = $shortcutPython + ',0'
    $shortcut.Save()
    $shortcutSaved = $shortcutShell.CreateShortcut($shortcutPath)
    [PSCustomObject]@{
        Path = $shortcutPath
        Target = $shortcutSaved.TargetPath
        Arguments = $shortcutSaved.Arguments
        WorkingDirectory = $shortcutSaved.WorkingDirectory
    }
}
