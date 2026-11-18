[CmdletBinding()]
param(
    [string]$AppRoot = (Join-Path $PSScriptRoot '..\..'),
    [string]$StateDirectory = (Join-Path $env:ProgramData 'PageManager'),
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Register production updates from an Administrator server console.'
}
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
$StateDirectory = [IO.Path]::GetFullPath($StateDirectory)
if (!$AppRoot.StartsWith(([IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase) -or
    $AppRoot -match '["\r\n]' -or $StateDirectory -match '["\r\n]') { throw 'Use protected server paths.' }
$python = Join-Path $AppRoot '.venv\Scripts\python.exe'
$script = Join-Path $AppRoot 'scripts\public_updates.py'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $script) -or !(Test-Path -LiteralPath (Join-Path $StateDirectory 'server.env'))) {
    throw 'Install and validate the restored server first.'
}
$name = 'PageManager-Updates'
$description = "PageManager public releases: $AppRoot"
$existing = Get-ScheduledTask -TaskPath '\PageManager\' -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) { throw 'A different updater task already uses this name.' }
$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}" --state-dir "{1}"' -f $script,$StateDirectory) -WorkingDirectory $AppRoot
$triggers = @((New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)))
$principal = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskPath '\PageManager\' -TaskName $name -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description $description -Force | Out-Null
if ($Start) { Start-ScheduledTask -TaskPath '\PageManager\' -TaskName $name }
else { Disable-ScheduledTask -TaskPath '\PageManager\' -TaskName $name | Out-Null }
Write-Host 'Public release updater registered; no inbound deployment port or GitHub token needed.'
