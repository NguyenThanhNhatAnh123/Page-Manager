param([switch]$Build)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimeDir = Join-Path $PSScriptRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath '.env')) { throw 'Run setup.ps1 first.' }
if ($Build) {
    Push-Location 'frontend'
    try { & npm.cmd run build; if ($LASTEXITCODE) { throw 'Frontend build failed.' } } finally { Pop-Location }
    if (Test-Path -LiteralPath '.tools\cargo\bin\cargo.exe') {
        $env:CARGO_HOME = Join-Path $PSScriptRoot '.tools\cargo'
        $env:RUSTUP_HOME = Join-Path $PSScriptRoot '.tools\rustup'
        $portableToolchain = Join-Path $PSScriptRoot '.tools\rustup\toolchains\1.90.0-x86_64-pc-windows-msvc'
        $portableCrt = Join-Path $PSScriptRoot '.tools\linker\VC\Tools\MSVC\14.44.35207\lib\x64'
        if ((Test-Path -LiteralPath $portableToolchain) -and (Test-Path -LiteralPath $portableCrt)) {
            $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = Join-Path $portableToolchain 'lib\rustlib\x86_64-pc-windows-msvc\bin\rust-lld.exe'
            $env:LIB = "$portableCrt;$PSScriptRoot\.tools\linker\sdk\c\um\x64;$PSScriptRoot\.tools\linker\sdk\c\ucrt\x64"
            & '.\.tools\cargo\bin\cargo.exe' '+1.90.0-x86_64-pc-windows-msvc' build --locked --manifest-path gateway/Cargo.toml
        } else { & '.\.tools\cargo\bin\cargo.exe' build --locked --manifest-path gateway/Cargo.toml }
    } else { & cargo build --manifest-path gateway/Cargo.toml }
    if ($LASTEXITCODE) { throw 'Rust build failed.' }
}
$pgCtl = Join-Path $PSScriptRoot '.tools\postgres\pgsql\bin\pg_ctl.exe'
$pgData = Join-Path $runtimeDir 'postgres'
if ((Test-Path -LiteralPath $pgCtl) -and (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION'))) {
    & $pgCtl -D $pgData status *> $null
    if ($LASTEXITCODE) { & $pgCtl -D $pgData -l (Join-Path $runtimeDir 'postgres.log') -o '-h 127.0.0.1 -p 55432' -w start }
}
$gateway = Join-Path $PSScriptRoot 'gateway\target\debug\pagemanager-gateway.exe'
if (!(Test-Path -LiteralPath $gateway)) { throw 'Build Rust gateway first: start.ps1 -Build' }
$worker = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','worker.app:app','--host','127.0.0.1','--port','8021','--workers','1','--no-access-log') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'worker.out.log') -RedirectStandardError (Join-Path $runtimeDir 'worker.err.log') -PassThru
try {
    & $gateway
} finally {
    if (!$worker.HasExited) { Stop-Process -Id $worker.Id }
}
