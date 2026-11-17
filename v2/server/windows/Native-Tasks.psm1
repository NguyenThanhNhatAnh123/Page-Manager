function Register-PageManagerRuntime {
    [CmdletBinding()]
    param([string]$PythonExe,[string]$RuntimeScript,[string]$ConfigFile,[string]$GatewayExe,[string]$StateDirectory,[string]$AppRoot,
          [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName='PageManager-v2')
    foreach ($path in @($PythonExe,$RuntimeScript,$ConfigFile,$GatewayExe,$StateDirectory,$AppRoot)) {
        if ($path -match '["\r\n]') { throw 'Unsupported path characters.' }
    }
    $taskPath = '\PageManager\'
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    try { $null = $scheduler.GetFolder('\PageManager') } catch { $null = $scheduler.GetFolder('\').CreateFolder('PageManager') }
    $description = "PageManager native v2: $AppRoot"
    $existing = Get-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing -and $existing.Description -ne $description) { throw 'A different task already uses this name.' }
    if ($existing -and (Get-PageManagerInstances -TaskName $TaskName) -gt 0) { throw 'Stop the existing native runtime before updating.' }
    $arguments = '"{0}" --config "{1}" --gateway "{2}" --state-dir "{3}"' -f $RuntimeScript,$ConfigFile,$GatewayExe,$StateDirectory
    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arguments -WorkingDirectory $AppRoot
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description -Force | Out-Null
}

function Get-PageManagerInstances {
    param([ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName='PageManager-v2')
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $task = $scheduler.GetFolder('\PageManager').GetTask($TaskName)
    return $task.GetInstances(0).Count
}

function Start-PageManagerRuntime {
    param([string]$StateDirectory,[ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName='PageManager-v2')
    $stopFile = Join-Path $StateDirectory 'stop.request'
    if (Test-Path -LiteralPath $stopFile) { Remove-Item -LiteralPath $stopFile }
    Enable-ScheduledTask -TaskPath '\PageManager\' -TaskName $TaskName | Out-Null
    Start-ScheduledTask -TaskPath '\PageManager\' -TaskName $TaskName
}

function Stop-PageManagerRuntime {
    param([string]$StateDirectory,[ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName='PageManager-v2')
    Disable-ScheduledTask -TaskPath '\PageManager\' -TaskName $TaskName | Out-Null
    [IO.File]::WriteAllText((Join-Path $StateDirectory 'stop.request'),'stop')
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ((Get-PageManagerInstances -TaskName $TaskName) -gt 0 -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 1 }
    if ((Get-PageManagerInstances -TaskName $TaskName) -gt 0) { throw 'Native runtime is still stopping; inspect logs before forcing termination.' }
}

Export-ModuleMember -Function Register-PageManagerRuntime,Get-PageManagerInstances,Start-PageManagerRuntime,Stop-PageManagerRuntime
