<#
.SYNOPSIS
  Remove the per-user install: program folder, shortcuts and the HKCU Run value.
.PARAMETER DryRun
  Only print the actions.
#>
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'
# Same key/value as src/handcontrol/windows/startup.py (RUN_KEY, VALUE_NAME).
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$valueName = 'Holoscobe'
$target = Join-Path $env:LOCALAPPDATA 'Programs\Holoscobe'
$links = @((Join-Path ([Environment]::GetFolderPath('Programs')) 'Holoscobe.lnk'),
           (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Holoscobe.lnk'))

function Do-Step([string]$text, [scriptblock]$action) {
    if ($DryRun) { Write-Output "[DryRun] $text" } else { Write-Output $text; & $action }
}

Get-Process -Name Holoscobe -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($target, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { $p = $_; Do-Step "Stop process $($p.Id)" { $p | Stop-Process -Force } }

if (Get-ItemProperty -Path $runKey -Name $valueName -ErrorAction SilentlyContinue) {
    Do-Step "Remove registry value $runKey\$valueName" { Remove-ItemProperty -Path $runKey -Name $valueName }
} else { Write-Output "No Run value '$valueName'." }
foreach ($l in $links) {
    if (Test-Path -LiteralPath $l) { Do-Step "Delete $l" { Remove-Item -LiteralPath $l -Force } }
}
if (Test-Path -LiteralPath $target) {
    Do-Step "Delete $target" { Remove-Item -LiteralPath $target -Recurse -Force }
} else { Write-Output "Not installed: $target" }
Write-Output 'User settings/logs (if any) are kept.'
