# Run on the already restored Windows SERVER. This never installs services or changes DNS.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Bundle,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
    [string]$StateDirectory = (Join-Path $env:ProgramData 'PageManager'),
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName = 'PageManager-v2',
    [ValidateRange(5,300)][int]$HealthTimeoutSeconds = 120,
    # Explicit operator-only migration. The automatic updater never supplies this.
    [string]$VideoDestination
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (![Security.Principal.WindowsIdentity]::GetCurrent().IsSystem -and
    !([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run on the Windows server with native deployment privileges.'
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE) { throw "Deployment command failed: $([IO.Path]::GetFileName($Executable))." }
}
function Assert-CodePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $prefix = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
    if (!$full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Code must be inside Program Files.' }
    $cursor = $full
    while ($cursor.Length -ge $prefix.Length) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Release paths must not contain junctions or symlinks.'
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $full
}
function Wait-AppHealthy {
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    do {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8020/healthz' -TimeoutSec 3
            if ($health.ok -and $health.database -and $health.worker) { return }
        } catch { }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Deployment health check timed out.'
}

$StateDirectory = [IO.Path]::GetFullPath($StateDirectory)
$config = Join-Path $StateDirectory 'server.env'
if (!(Test-Path -LiteralPath $config)) { throw 'Restore and validate the existing server first.' }
$lock = [IO.File]::Open((Join-Path $StateDirectory 'deploy.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$pausedHere=$false
$pause=Join-Path $StateDirectory 'updates.paused'
try {
    $task = Get-ScheduledTask -TaskPath '\PageManager\' -TaskName $TaskName
    if ($task.Actions.Count -ne 1) { throw 'Unexpected native task actions.' }
    $previous = Assert-CodePath $task.Actions[0].WorkingDirectory
    if ($task.Description -ne "PageManager native v2: $previous") { throw 'Unexpected native task ownership.' }
    $python = Join-Path $previous '.venv\Scripts\python.exe'
    if ($task.Actions[0].Execute -ne $python) { throw 'Unexpected task interpreter.' }
    Import-Module (Join-Path $previous 'server\windows\Native-Tasks.psm1') -Force
    if ($task.State -ne 'Running' -or (Get-PageManagerInstances -TaskName $TaskName) -eq 0 -or
        (Test-Path -LiteralPath (Join-Path $StateDirectory 'stop.request'))) {
        throw 'The server was stopped by an operator; automatic deployment will not start it.'
    }
    Wait-AppHealthy
    $id = $ExpectedCommit + '-' + [Guid]::NewGuid().ToString('N')
    $release = Assert-CodePath (Join-Path $env:ProgramFiles "PageManager-releases\$id")
    $newApp = Join-Path $release 'v2'
    $newPython = Join-Path $newApp '.venv\Scripts\python.exe'
    $gateway = Join-Path $newApp 'bin\pagemanager-gateway.exe'
    $audit = Join-Path $StateDirectory "deployments\$id"
    New-Item -ItemType Directory -Path $audit -Force | Out-Null
    $savedTask = Join-Path $audit 'previous-task.xml'
    Export-ScheduledTask -TaskName $TaskName -TaskPath '\PageManager\' | Set-Content -LiteralPath $savedTask -Encoding Unicode
    $baseline = Join-Path $audit 'baseline.json'
    $stateScript = Join-Path $previous 'scripts\deployment_state.py'
    $videoScript = Join-Path $newApp 'scripts\video_storage.py'
    $videoJournal = Join-Path $audit 'video-migration.json'
    $configBackup = Join-Path $audit 'previous.env'
    $maintenance = Join-Path $StateDirectory 'video-storage.maintenance'
    $pause = Join-Path $StateDirectory 'updates.paused'
    $pausedHere = $false
    Invoke-Checked $python @((Join-Path $previous 'scripts\release_bundle.py'), '--bundle', $Bundle,
        '--commit', $ExpectedCommit, '--sha256', $ExpectedSha256, '--destination', $release)
    if ($VideoDestination) {
        if (Test-Path -LiteralPath $maintenance) { throw 'An earlier storage maintenance requires inspection.' }
        if (!(Test-Path -LiteralPath $pause)) { [IO.File]::WriteAllText($pause,'Video storage migration'); $pausedHere=$true }
        Copy-Item -LiteralPath $config -Destination $configBackup
        Invoke-Checked $python @('-c', 'import sys;sys.path.insert(0,sys.argv[1]);from scripts.deployment_state import validate_settings;validate_settings(*sys.argv[2:])', $newApp, $config, $newApp, $previous)
        $VideoDestination=[IO.Path]::GetFullPath($VideoDestination)
        if ($VideoDestination -eq [IO.Path]::GetPathRoot($VideoDestination)) { throw 'Use a dedicated directory, not the volume root.' }
        $cursor=$VideoDestination
        while ($cursor) {
            if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Linked video directories are forbidden.' }
            $cursor=Split-Path -Parent $cursor
        }
        $marker=Join-Path $VideoDestination '.pagemanager-video-root'
        if ((Test-Path -LiteralPath $VideoDestination) -and @(Get-ChildItem -LiteralPath $VideoDestination -Force).Count -and !(Test-Path -LiteralPath $marker)) { throw 'Video destination contains unrelated data.' }
        New-Item -ItemType Directory -Path $VideoDestination -Force | Out-Null
        $acl=New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true,$false)
        foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
            $identity=New-Object Security.Principal.SecurityIdentifier($sid)
            $rule=New-Object Security.AccessControl.FileSystemAccessRule($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
            $acl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $VideoDestination -AclObject $acl
        [IO.File]::WriteAllText($marker,'PageManager private video storage')
        $volume=Get-Volume -DriveLetter $VideoDestination.Substring(0,1)
        if ($volume.FileSystem -ne 'NTFS' -or $volume.HealthStatus -ne 'Healthy' -or $volume.DriveType -ne 'Fixed') { throw 'Healthy fixed NTFS video volume required.' }
    } else {
        Invoke-Checked $python @($stateScript, '--config', $config, '--release', $newApp, '--previous', $previous)
    }
    Invoke-Checked $python @('-m', 'venv', (Join-Path $newApp '.venv'))
    Invoke-Checked $newPython @('-m', 'pip', 'install', '--no-index', '--find-links', (Join-Path $release 'wheelhouse'),
        '-r', (Join-Path $newApp 'requirements-lock.txt'))
    Invoke-Checked $newPython @('-m', 'pip', 'check')
    Invoke-Checked $newPython @('-c', 'import psycopg, cryptography.fernet, argon2, PIL, fastapi, uvicorn')
    Invoke-Checked $gateway @('--version')
    $switched = $false
    $stopped = $false
    $committed = $false
    $applyAttempted = $false
    try {
        if ($VideoDestination) {
            Invoke-Checked $newPython @($videoScript,'stage','--config',$config,'--destination',$VideoDestination,'--journal',$videoJournal)
            [IO.File]::WriteAllText($maintenance,'Video storage migration')
            $stopped=$true
            Invoke-Checked $newPython @($videoScript,'quiesce','--config',$config,'--previous',$previous,'--state',$StateDirectory,'--task',$TaskName,'--journal',$videoJournal)
            $applyAttempted=$true
            Invoke-Checked $newPython @($videoScript,'switch','--config',$config,'--destination',$VideoDestination,'--state',$StateDirectory,'--journal',$videoJournal)
        } else {
            Stop-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
            $stopped = $true
            Invoke-Checked $python @($stateScript, '--config', $config, '--write', $baseline)
        }
        Register-PageManagerRuntime -PythonExe $newPython -RuntimeScript (Join-Path $newApp 'scripts\native_runtime.py') `
            -ConfigFile $config -GatewayExe $gateway -StateDirectory $StateDirectory -AppRoot $newApp `
            -TaskName $TaskName -PreviousAppRoot $previous
        $switched = $true
        Start-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
        Wait-AppHealthy
        if ($VideoDestination) {
            Invoke-Checked $newPython @($videoScript,'verify','--config',$config,'--journal',$videoJournal)
            $committed=$true
            # The original files are removed only after the switched system has
            # passed health, all-account HTTP reads and protected-data checks.
            Invoke-Checked $newPython @($videoScript,'cleanup','--config',$config,'--journal',$videoJournal)
            Remove-Item -LiteralPath $maintenance
            @{current=$ExpectedCommit;previous=$null;failed=$null} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StateDirectory 'updater.json') -Encoding UTF8
        } else { Invoke-Checked $python @($stateScript, '--config', $config, '--compare', $baseline) }
        [pscustomobject]@{ commit=$ExpectedCommit; release=$release; previous=$previous; status='healthy' } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $audit 'result.json') -Encoding UTF8
        Write-Host "Deployed $ExpectedCommit. Previous code and private configuration retained."
    } catch {
        $failure = $_
        if ($stopped -and !$committed) {
            if ($switched) { Stop-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName }
            if ($VideoDestination) {
                if ($applyAttempted -and (Get-Content -LiteralPath $videoJournal -Raw | ConvertFrom-Json).phase -ne 'copied') {
                    Invoke-Checked $newPython @($videoScript,'rollback','--config',$config,'--journal',$videoJournal)
                }
                [IO.File]::WriteAllBytes($config,[IO.File]::ReadAllBytes($configBackup))
                if (Test-Path -LiteralPath $maintenance) { Remove-Item -LiteralPath $maintenance }
            }
            Register-ScheduledTask -TaskName $TaskName -TaskPath '\PageManager\' -Xml (Get-Content -LiteralPath $savedTask -Raw) -Force | Out-Null
            Start-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
            Wait-AppHealthy
            if (!$VideoDestination -and (Test-Path -LiteralPath $baseline)) { Invoke-Checked $python @($stateScript, '--config', $config, '--compare', $baseline) }
            [pscustomobject]@{ commit=$ExpectedCommit; release=$release; previous=$previous; status='rolled_back' } |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $audit 'result.json') -Encoding UTF8
            Write-Warning 'Previous native task restored and healthy; protected account and Reel history retained.'
        } elseif ($committed) {
            if (Test-Path -LiteralPath $maintenance) { Remove-Item -LiteralPath $maintenance }
            [pscustomobject]@{commit=$ExpectedCommit;release=$release;previous=$previous;status='healthy_cleanup_pending'} |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $audit 'result.json') -Encoding UTF8
        }
        throw $failure
    }
} finally {
    if ($pausedHere -and (Test-Path -LiteralPath $pause)) { Remove-Item -LiteralPath $pause }
    $lock.Dispose()
}
