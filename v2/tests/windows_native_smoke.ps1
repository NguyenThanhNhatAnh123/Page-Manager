# CI only: a fresh private cluster, fake provider data, no Meta calls or real users.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'This disposable integration script runs only on GitHub-hosted runners.' }
$appRoot = (Get-Location).Path
$testRoot = Join-Path $env:RUNNER_TEMP 'pagemanager-native-ci'
New-Item -ItemType Directory -Path $testRoot | Out-Null
$pgBin = $env:PGBIN
if (!$pgBin) { throw 'Official PostgreSQL Windows tools not found.' }
$pgVersion = & (Join-Path $pgBin 'postgres.exe') --version
if ($LASTEXITCODE -or $pgVersion -notmatch 'PostgreSQL\) 18\.') { throw 'Use PostgreSQL major 18 for native CI.' }
$pgData = Join-Path $testRoot 'postgres'
$pythonExe = (Get-Command python.exe).Source
$gateway = Join-Path $appRoot 'gateway\target\release\pagemanager-gateway.exe'
$runtime = Join-Path $appRoot 'scripts\native_runtime.py'
$taskName = "PageManager-CI-$env:GITHUB_RUN_ID"
$taskCreated = $false
$foreground = $null

function Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE) { throw "CI command failed: $([IO.Path]::GetFileName($Exe))" }
}
function Wait-Healthy {
    $deadline = [DateTime]::UtcNow.AddSeconds(100)
    do {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8020/healthz' -TimeoutSec 2
            if ($health.ok -and $health.database -and $health.worker) { return }
        } catch { }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Native health check timed out.'
}
function Write-Configuration([string]$State, [string]$Dsn) {
    New-Item -ItemType Directory -Path $State | Out-Null
    $values = [ordered]@{
        DATABASE_URL=$Dsn
        PM_INTERNAL_KEY=('native-ci-only-' + ('a' * 64))
        PM_ENCRYPTION_KEY='YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE='
        PM_DATA_DIR=(Join-Path $State 'data').Replace('\','/')
        PM_FRONTEND_DIR=(Join-Path $appRoot 'frontend\dist').Replace('\','/')
        PM_PUBLIC_ORIGIN='http://127.0.0.1:8020'
        PM_COOKIE_SECURE='false'
        PM_LISTEN='127.0.0.1:8020'
        PM_WORKER_URL='http://127.0.0.1:8021'
        PM_NATIVE_SERVER='1'
    }
    $path = Join-Path $State 'server.env'
    [IO.File]::WriteAllLines($path, @($values.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }))
    return $path
}

try {
    Checked (Join-Path $pgBin 'initdb.exe') @('-D',$pgData,'-U','postgres','-A','trust','--encoding=UTF8','--locale=C')
    Checked (Join-Path $pgBin 'pg_ctl.exe') @('-D',$pgData,'-l',(Join-Path $testRoot 'postgres.log'),'-o','-h 127.0.0.1 -p 55433','-w','start')
    # Storage fixtures deliberately reset their own schemas. Keep them out of
    # the worker dataset subsequently reused by the real gateway isolation tests.
    Checked (Join-Path $pgBin 'createdb.exe') @('-h','127.0.0.1','-p','55433','-U','postgres','native_video_storage')
    $env:PM_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55433/native_video_storage'
    $env:DATABASE_URL = $env:PM_TEST_DATABASE_URL
    Checked $pythonExe @('-m','pytest','tests/test_video_library.py','tests/test_video_storage.py','tests/test_video_uploads.py','-q')
    $env:PM_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55433/postgres'
    $env:DATABASE_URL = $env:PM_TEST_DATABASE_URL
    Checked $pythonExe @('-m','pytest','tests/test_worker.py','tests/test_mcp_page_edits.py','tests/test_page_images.py','tests/test_server.py','tests/test_windows_native.py','tests/test_transfer_windows.py','tests/test_deployment.py','tests/test_public_updates.py','-q')
    $state = Join-Path $testRoot 'foreground'
    $config = Write-Configuration $state $env:PM_TEST_DATABASE_URL
    $foreground = Start-Process -FilePath $pythonExe -ArgumentList ('"{0}" --config "{1}" --gateway "{2}" --state-dir "{3}" --worker-module tests.runtime_server:app' -f $runtime,$config,$gateway,$state) -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru
    Wait-Healthy
    $env:PM_TEST_GATEWAY_URL = 'http://127.0.0.1:8020'
    Checked $pythonExe @('-m','pytest','tests/test_gateway.py','-q')
    [IO.File]::WriteAllText((Join-Path $state 'stop.request'),'stop')
    if (!$foreground.WaitForExit(60000) -or $foreground.ExitCode -ne 0) { throw 'Foreground runtime did not shut down cleanly.' }
    $foreground = $null

    # SYSTEM task uses a separate empty database, so no provider sources exist.
    Checked (Join-Path $pgBin 'createdb.exe') @('-h','127.0.0.1','-p','55433','-U','postgres','native_startup')
    $taskState = Join-Path $testRoot 'startup'
    $taskConfig = Write-Configuration $taskState 'postgresql://postgres@127.0.0.1:55433/native_startup'
    Import-Module (Join-Path $appRoot 'server\windows\Native-Tasks.psm1') -Force
    Register-PageManagerRuntime -PythonExe $pythonExe -RuntimeScript $runtime -ConfigFile $taskConfig -GatewayExe $gateway -StateDirectory $taskState -AppRoot $appRoot -TaskName $taskName
    $taskCreated = $true
    Start-PageManagerRuntime -StateDirectory $taskState -TaskName $taskName
    Wait-Healthy
    # A real child crash must recover inside the same SYSTEM task instance,
    # independently of whether Task Scheduler honors nonzero-exit retries.
    $sameTaskRun=(Get-ScheduledTaskInfo -TaskPath '\PageManager\' -TaskName $taskName).LastRunTime
    $ownedGateway=Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8020 -State Listen
    $oldGatewayPid=[int]$ownedGateway.OwningProcess
    $ownedProcess=Get-CimInstance Win32_Process -Filter ('ProcessId='+$oldGatewayPid)
    if($ownedProcess.ExecutablePath -ne $gateway){throw 'Refusing to stop an unrelated CI process'}
    Stop-Process -Id $oldGatewayPid -Force
    Wait-Healthy
    $newGatewayPid=[int](Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8020 -State Listen).OwningProcess
    if($newGatewayPid -eq $oldGatewayPid -or (Get-ScheduledTaskInfo -TaskPath '\PageManager\' -TaskName $taskName).LastRunTime -ne $sameTaskRun){throw 'Supervisor failed to recover within the same task instance'}
    $credentials = Join-Path $taskState 'data\initial-users.txt'
    $before = (Get-FileHash -LiteralPath $credentials).Hash
    $count = & (Join-Path $pgBin 'psql.exe') -h 127.0.0.1 -p 55433 -U postgres -d native_startup -tAc 'SELECT COUNT(*) FROM public.pm_users'
    if ($LASTEXITCODE -or $count.Trim() -ne '20') { throw 'Expected exactly 20 initial users.' }
    Stop-PageManagerRuntime -StateDirectory $taskState -TaskName $taskName
    Start-PageManagerRuntime -StateDirectory $taskState -TaskName $taskName
    Wait-Healthy
    if ((Get-FileHash -LiteralPath $credentials).Hash -ne $before) { throw 'Restart replaced initial credentials.' }
    Stop-PageManagerRuntime -StateDirectory $taskState -TaskName $taskName

    # Parse native scripts and validate the exact domain without requesting real TLS.
    foreach ($file in Get-ChildItem server/windows,scripts -Include *.ps1,*.psm1 -Recurse) {
        $tokens=$null; $errors=$null
        $null=[Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)
        if ($errors.Count) { throw 'Invalid native PowerShell script.' }
    }
    $caddy = Join-Path $testRoot 'caddy.exe'
    Invoke-WebRequest 'https://caddyserver.com/api/download?os=windows&arch=amd64' -OutFile $caddy
    Checked $caddy @('version')
    Checked $pythonExe @('server/windows/configure.py','init','--app-root',$appRoot,'--state-dir',(Join-Path $testRoot 'https'))
    Checked $caddy @('validate','--config',(Join-Path $testRoot 'https\Caddyfile'),'--adapter','caddyfile')
    Write-Host 'Windows native runtime, SYSTEM startup/restart, 20 accounts and HTTPS config verified. No reboot, public DNS/TLS or Meta test performed.'
} finally {
    if ($foreground -and !$foreground.HasExited) {
        [IO.File]::WriteAllText((Join-Path $state 'stop.request'),'stop')
        if (!$foreground.WaitForExit(60000)) { Stop-Process -Id $foreground.Id -Force }
    }
    if ($taskCreated) {
        try { Stop-PageManagerRuntime -StateDirectory $taskState -TaskName $taskName } finally {
            Unregister-ScheduledTask -TaskPath '\PageManager\' -TaskName $taskName -Confirm:$false
        }
    }
    if (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION')) {
        & (Join-Path $pgBin 'pg_ctl.exe') -D $pgData -m fast -w stop
    }
}
