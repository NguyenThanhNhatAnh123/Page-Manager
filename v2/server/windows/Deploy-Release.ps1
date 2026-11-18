# Run on the already restored Windows SERVER. This never installs services or changes DNS.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Bundle,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
    [string]$StateDirectory = (Join-Path $env:ProgramData 'PageManager'),
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName = 'PageManager-v2',
    [ValidateRange(5,300)][int]$HealthTimeoutSeconds = 120
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
    Invoke-Checked $python @((Join-Path $previous 'scripts\release_bundle.py'), '--bundle', $Bundle,
        '--commit', $ExpectedCommit, '--sha256', $ExpectedSha256, '--destination', $release)
    Invoke-Checked $python @($stateScript, '--config', $config, '--release', $newApp, '--previous', $previous)
    Invoke-Checked $python @('-m', 'venv', (Join-Path $newApp '.venv'))
    Invoke-Checked $newPython @('-m', 'pip', 'install', '--no-index', '--find-links', (Join-Path $release 'wheelhouse'),
        '-r', (Join-Path $newApp 'requirements-lock.txt'))
    Invoke-Checked $newPython @('-m', 'pip', 'check')
    Invoke-Checked $newPython @('-c', 'import psycopg, cryptography.fernet, argon2, PIL, fastapi, uvicorn')
    Invoke-Checked $gateway @('--version')
    $switched = $false
    $stopped = $false
    try {
        Stop-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
        $stopped = $true
        Invoke-Checked $python @($stateScript, '--config', $config, '--write', $baseline)
        Register-PageManagerRuntime -PythonExe $newPython -RuntimeScript (Join-Path $newApp 'scripts\native_runtime.py') `
            -ConfigFile $config -GatewayExe $gateway -StateDirectory $StateDirectory -AppRoot $newApp `
            -TaskName $TaskName -PreviousAppRoot $previous
        $switched = $true
        Start-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
        Wait-AppHealthy
        Invoke-Checked $python @($stateScript, '--config', $config, '--compare', $baseline)
        [pscustomobject]@{ commit=$ExpectedCommit; release=$release; previous=$previous; status='healthy' } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $audit 'result.json') -Encoding UTF8
        Write-Host "Deployed $ExpectedCommit. Previous code and private configuration retained."
    } catch {
        $failure = $_
        if ($stopped) {
            if ($switched) { Stop-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName }
            Register-ScheduledTask -TaskName $TaskName -TaskPath '\PageManager\' -Xml (Get-Content -LiteralPath $savedTask -Raw) -Force | Out-Null
            Start-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
            Wait-AppHealthy
            if (Test-Path -LiteralPath $baseline) { Invoke-Checked $python @($stateScript, '--config', $config, '--compare', $baseline) }
            Write-Warning 'Previous code restored and healthy. Database, media and server.env were not restored or reset.'
        }
        throw $failure
    }
} finally {
    $lock.Dispose()
}
