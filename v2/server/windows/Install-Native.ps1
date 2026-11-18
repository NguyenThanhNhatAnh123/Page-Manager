[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Check','Install','Start','Stop','Status')][string]$Action = 'Check',
    [string]$AppRoot = (Join-Path $PSScriptRoot '..\..'),
    [string]$StateDirectory = (Join-Path $env:ProgramData 'PageManager'),
    [string]$CaddyExe = 'C:\Program Files\Caddy\caddy.exe',
    [ValidateSet('Caddy','Tunnel')][string]$Ingress = 'Caddy',
    [string]$DatabaseAdminPasswordFile,
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$PostgresServiceName = 'postgresql-x64-18',
    [ValidateRange(1,65535)][int]$DatabasePort = 5432,
    [string]$Domain = 'eagleglobal2027.com',
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TaskName = 'PageManager-v2'
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Native-Tasks.psm1') -Force
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
$StateDirectory = [IO.Path]::GetFullPath($StateDirectory)
$pythonExe = Join-Path $AppRoot '.venv\Scripts\python.exe'
$gatewayExe = Join-Path $AppRoot 'bin\pagemanager-gateway.exe'
$runtimeScript = Join-Path $AppRoot 'scripts\native_runtime.py'
$configScript = Join-Path $AppRoot 'server\windows\configure.py'
$configFile = Join-Path $StateDirectory 'server.env'
$taskPath = '\PageManager\'
$serviceName = 'PageManagerHttps'
$administrator = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE) { throw "Command failed: $([IO.Path]::GetFileName($Executable)). Review the prerequisite checks and local logs." }
}

function Test-GatewayBundle {
    $manifestFile = Join-Path $AppRoot '..\manifest.json'
    if (!(Test-Path -LiteralPath $manifestFile) -or !(Test-Path -LiteralPath $gatewayExe)) { return $false }
    $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
    $entry = $manifest.files.PSObject.Properties['v2/bin/pagemanager-gateway.exe']
    if (!$entry -or $manifest.gateway_version_probe -ne $true) { return $false }
    return (Get-FileHash -LiteralPath $gatewayExe -Algorithm SHA256).Hash -eq $entry.Value.sha256
}

$bundleVerified = Test-GatewayBundle
$postgres = Get-Service -Name $PostgresServiceName -ErrorAction SilentlyContinue
$gatewaySignature = if (Test-Path -LiteralPath $gatewayExe) { (Get-AuthenticodeSignature -LiteralPath $gatewayExe).Status } else { 'Missing' }
$caddySignature = if (Test-Path -LiteralPath $CaddyExe) { (Get-AuthenticodeSignature -LiteralPath $CaddyExe).Status } else { 'Missing' }
if ($Action -eq 'Check') {
    [pscustomobject]@{
        Domain = $Domain
        PythonEnvironment = Test-Path -LiteralPath $pythonExe
        GatewayBundleHashVerified = $bundleVerified
        GatewaySignature = $gatewaySignature
        CaddySignature = $caddySignature
        PostgreSQLService = if ($postgres) { $postgres.Status } else { 'Missing' }
        Administrator = $administrator
        ConfigExists = Test-Path -LiteralPath $configFile
    } | Format-List
    if ($bundleVerified) {
        try { Invoke-Checked $gatewayExe @('--version') } catch { Write-Warning 'Gateway execution failed. If Smart App Control blocked it, obtain a trusted signed build; do not disable protection.' }
    }
    if (Test-Path -LiteralPath $CaddyExe) { try { Invoke-Checked $CaddyExe @('version') } catch { Write-Warning 'Caddy execution failed; verify source/signature and Windows policy.' } }
    if (Test-Path -LiteralPath $pythonExe) {
        try { Invoke-Checked $pythonExe @('-c','import psycopg, cryptography.fernet, argon2; print(''Python native dependencies: OK'')') }
        catch { Write-Warning 'Python native dependency import failed. Check trusted wheels and Windows application-control events before installing.' }
    }
    Write-Host 'Check complete. No services, scheduled tasks, firewall or security settings were changed.'
    return
}
if (!$administrator) { throw 'Run as Administrator on the SERVER. No changes were applied.' }
if ($Action -eq 'Install') {
    $programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
    if (!$AppRoot.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Extract the production bundle under Program Files before registering a SYSTEM task.' }
    if (!$bundleVerified) { throw 'Use the matching Windows bundle with manifest.json; the gateway hash/version probe could not be verified.' }
    if (!(Test-Path -LiteralPath $pythonExe) -or !$postgres -or ($Ingress -eq 'Caddy' -and !(Test-Path -LiteralPath $CaddyExe))) { throw 'Install Python dependencies, PostgreSQL service and the selected ingress prerequisites first. See README.' }
    Invoke-Checked $gatewayExe @('--version')
    if ($Ingress -eq 'Caddy') { Invoke-Checked $CaddyExe @('version') }
    Invoke-Checked $pythonExe @('-c','import psycopg, cryptography.fernet, argon2; print(''Python native dependencies: OK'')')
    if (!$PSCmdlet.ShouldProcess('Native PageManager server', 'Prepare private configuration and register automatic background startup')) { return }
    if (Test-Path -LiteralPath $StateDirectory) {
        $owner = (Get-Acl -LiteralPath $StateDirectory).GetOwner([Security.Principal.SecurityIdentifier]).Value
        $currentOwner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        if ($owner -notin @('S-1-5-18','S-1-5-32-544',$currentOwner)) { throw 'State directory has an unexpected owner. Choose a new private directory or review its ownership first.' }
    }
    Invoke-Checked $pythonExe @($configScript,'init','--app-root',$AppRoot,'--state-dir',$StateDirectory,'--domain',$Domain,'--db-port',"$DatabasePort")
    Set-Service -Name $PostgresServiceName -StartupType Automatic
    Start-Service -Name $PostgresServiceName
    $databaseArguments = @($configScript,'database','--state-dir',$StateDirectory)
    if ($DatabaseAdminPasswordFile) { $databaseArguments += @('--admin-password-file',$DatabaseAdminPasswordFile) }
    Invoke-Checked $pythonExe $databaseArguments
    if ($Ingress -eq 'Caddy') { Invoke-Checked $CaddyExe @('validate','--config',(Join-Path $StateDirectory 'Caddyfile'),'--adapter','caddyfile') }
    Register-PageManagerRuntime -PythonExe $pythonExe -RuntimeScript $runtimeScript -ConfigFile $configFile -GatewayExe $gatewayExe -StateDirectory $StateDirectory -AppRoot $AppRoot -TaskName $TaskName
    Disable-ScheduledTask -TaskPath $taskPath -TaskName $TaskName | Out-Null
    if ($Ingress -eq 'Caddy') {
        $binaryPath = '"{0}" run --config "{1}" --adapter caddyfile' -f $CaddyExe,(Join-Path $StateDirectory 'Caddyfile')
        $service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
        if ($service -and $service.PathName -ne $binaryPath) { throw 'A different HTTPS service already uses this name; refusing to replace it.' }
        if (!$service) { New-Service -Name $serviceName -BinaryPathName $binaryPath -DisplayName 'PageManager HTTPS' -StartupType Automatic | Out-Null }
        Invoke-Checked 'sc.exe' @('failure',$serviceName,'reset=','86400','actions=','restart/5000/restart/15000/restart/60000')
    }
    Write-Host 'Native task/service registered. Use -Action Start after checking DNS/ports. No firewall or DNS changes were made.'
    return
}
if ($Action -eq 'Start' -and $PSCmdlet.ShouldProcess($TaskName,'Start PageManager background task and HTTPS service')) {
    if (!(Test-Path -LiteralPath $configFile)) { throw 'Install the native server first.' }
    Start-Service -Name $PostgresServiceName
    Start-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
    if ($Ingress -eq 'Caddy') { Start-Service -Name $serviceName }
}
if ($Action -eq 'Stop' -and $PSCmdlet.ShouldProcess($TaskName,'Stop native app task; preserve all data')) {
    Stop-PageManagerRuntime -StateDirectory $StateDirectory -TaskName $TaskName
}
if ($Action -eq 'Status' -or $Action -eq 'Start' -or $Action -eq 'Stop') {
    Get-ScheduledTask -TaskPath $taskPath -TaskName $TaskName | Select-Object TaskName,State
    $serviceNames = @($PostgresServiceName)
    if ($Ingress -eq 'Caddy') { $serviceNames += $serviceName }
    Get-Service -Name $serviceNames | Select-Object Name,Status,StartType
    try { Invoke-RestMethod 'http://127.0.0.1:8020/healthz' -TimeoutSec 10 | Format-List } catch { Write-Host 'App not healthy/reachable yet. Inspect the private logs.' }
}
