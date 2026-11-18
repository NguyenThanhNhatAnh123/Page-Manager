[CmdletBinding()]
param([Parameter(Mandatory)][string]$ArtifactDirectory)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Send deployments only from a trusted GitHub-hosted production job.'
}
if ($env:PM_DEPLOY_HOST -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]*$' -or
    $env:PM_DEPLOY_USER -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]*$' -or
    $env:PM_DEPLOY_COMMIT -notmatch '^[0-9a-f]{40}$' -or
    !$env:PM_DEPLOY_SSH_KEY -or !$env:PM_DEPLOY_KNOWN_HOSTS) { throw 'Production SSH settings are incomplete or invalid.' }
$port = if ($env:PM_DEPLOY_PORT) { [int]$env:PM_DEPLOY_PORT } else { 22 }
if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid SSH port.' }
$bundle = Join-Path $ArtifactDirectory 'PageManager-windows-x64.zip'
$hash = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumLine = (Get-Content -LiteralPath (Join-Path $ArtifactDirectory 'SHA256SUMS.txt') -Raw).Trim()
if ($checksumLine -cne "$hash  PageManager-windows-x64.zip") { throw 'Downloaded artifact checksum mismatch.' }
$temporary = Join-Path $env:RUNNER_TEMP ('pm-ssh-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$identity = Join-Path $temporary 'identity'
$knownHosts = Join-Path $temporary 'known_hosts'
try {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $temporary /inheritance:r /grant:r "*$($sid):(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE) { throw 'Cannot secure temporary SSH files.' }
    [IO.File]::WriteAllText($identity, $env:PM_DEPLOY_SSH_KEY.Replace("`r", '').TrimEnd() + "`n")
    [IO.File]::WriteAllText($knownHosts, $env:PM_DEPLOY_KNOWN_HOSTS.TrimEnd() + "`n")
    $env:PM_DEPLOY_SSH_KEY = $null
    $target = "$env:PM_DEPLOY_USER@$env:PM_DEPLOY_HOST"
    $sshOptions = @('-i', $identity, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', "UserKnownHostsFile=$knownHosts", '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=15')
    function Invoke-Remote([string]$Command) {
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("`$ErrorActionPreference='Stop'; " + $Command))
        & ssh.exe @sshOptions -p $port $target powershell.exe -NoProfile -NonInteractive -EncodedCommand $encoded
        if ($LASTEXITCODE) { throw 'Windows remote deployment failed. Inspect the server deployment audit directory.' }
    }
    Invoke-Remote "if (!(Test-Path -LiteralPath 'C:/ProgramData/PageManager/server.env')) { throw 'Restore the server first.' }; New-Item -ItemType Directory -Path 'C:/ProgramData/PageManager/incoming' -Force | Out-Null"
    $remoteBundle = 'C:/ProgramData/PageManager/incoming/' + $env:PM_DEPLOY_COMMIT + '.zip'
    & scp.exe @sshOptions -P $port $bundle ('{0}:{1}' -f $target,$remoteBundle)
    if ($LASTEXITCODE) { throw 'Release upload failed.' }
    # The bootstrap script is installed once under Program Files by the server operator.
    Invoke-Remote "& 'C:/Program Files/PageManager/v2/server/windows/Deploy-Release.ps1' -Bundle '$remoteBundle' -ExpectedCommit '$env:PM_DEPLOY_COMMIT' -ExpectedSha256 '$hash'"
} finally {
    $env:PM_DEPLOY_SSH_KEY = $null
    # Only the two files created by this invocation are deleted. No recursive cleanup.
    foreach ($path in @($identity, $knownHosts)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
    Remove-Item -LiteralPath $temporary -Force
}
