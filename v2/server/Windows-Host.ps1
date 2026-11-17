[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$EnableHyperV,
    [switch]$ConfigureAlwaysOn,
    [string]$VMName
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this script on the Windows 11 server.' }
$osInfo = Get-CimInstance Win32_OperatingSystem
$computerInfo = Get-CimInstance Win32_ComputerSystem
$cpuInfo = @(Get-CimInstance Win32_Processor)
$edition = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID
$supportedEdition = $edition -match '^(Professional|Enterprise|Education)'
$isWindows11 = $osInfo.ProductType -eq 1 -and [int]$osInfo.BuildNumber -ge 22000
$hyperV = Get-CimInstance Win32_OptionalFeature -Filter "Name='Microsoft-Hyper-V-All'" -ErrorAction SilentlyContinue
$administrator = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
[pscustomobject]@{
    Windows = $osInfo.Caption
    Edition = $edition
    Windows11HyperVEdition = [bool]($isWindows11 -and $supportedEdition)
    MemoryGB = [math]::Round($computerInfo.TotalPhysicalMemory / 1GB, 1)
    LogicalProcessors = ($cpuInfo | Measure-Object NumberOfLogicalProcessors -Sum).Sum
    HypervisorPresent = [bool]$computerInfo.HypervisorPresent
    VirtualizationInFirmware = [bool]($cpuInfo.VirtualizationFirmwareEnabled -contains $true)
    HyperVEnabled = [bool]($hyperV -and $hyperV.InstallState -eq 1)
    Administrator = $administrator
} | Format-List

if (!$EnableHyperV -and !$ConfigureAlwaysOn -and !$VMName) {
    Write-Host 'Read-only check complete. Recommended host: 16+ GB RAM; guest: 4 vCPU, 8 GB RAM, 200+ GB SSD.'
    Write-Host 'Guide: v2/server/README.md. No settings were changed.'
    return
}
if (!$isWindows11 -or !$supportedEdition) { throw 'Hyper-V host setup requires supported Windows 11 Pro/Enterprise/Education. Check the guide for Windows Home.' }
if (!$administrator) { throw 'Open PowerShell as Administrator on the SERVER before applying host settings.' }
if ($EnableHyperV -and $PSCmdlet.ShouldProcess('Windows 11 server', 'Enable Hyper-V; restart is manual')) {
    $result = Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All -NoRestart
    Write-Host "Hyper-V enabled. Restart needed: $($result.RestartNeeded). Restart the server yourself when ready."
}
if ($ConfigureAlwaysOn -and $PSCmdlet.ShouldProcess('Windows 11 server on AC power', 'Disable automatic sleep and hibernation timeout')) {
    & powercfg.exe /change standby-timeout-ac 0
    if ($LASTEXITCODE) { throw 'Could not update AC sleep timeout.' }
    & powercfg.exe /change hibernate-timeout-ac 0
    if ($LASTEXITCODE) { throw 'Could not update AC hibernation timeout.' }
    Write-Host 'AC sleep/hibernation timeouts disabled. Updates and security protections remain enabled.'
}
if ($VMName) {
    Import-Module Hyper-V
    $selectedVm = @(Get-VM -Name $VMName | Where-Object Name -eq $VMName)
    if ($selectedVm.Count -ne 1) { throw 'Expected exactly one existing VM with this exact name.' }
    if ($PSCmdlet.ShouldProcess($VMName, 'Configure automatic VM start and graceful guest shutdown')) {
        $selectedVm[0] | Set-VM -AutomaticStartAction Start -AutomaticStartDelay 30 -AutomaticStopAction ShutDown
        Write-Host 'VM will start after Windows boots, including before user login.'
    }
}
