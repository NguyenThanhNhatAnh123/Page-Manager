[CmdletBinding()]
param([Parameter(Mandatory)][string]$AppRoot,[Parameter(Mandatory)][string]$StateDirectory,
      [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName='PageManager-v2')
$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskPath '\PageManager\' -TaskName $TaskName
if ($task.Description -ne "PageManager native v2: $AppRoot" -or $task.Actions[0].WorkingDirectory -ne $AppRoot) { throw 'Unexpected native task ownership.' }
Import-Module (Join-Path $PSScriptRoot 'Native-Tasks.psm1') -Force
Stop-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
