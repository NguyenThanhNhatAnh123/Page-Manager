param([switch]$Portable)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) { & python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
$setupArgs = @('scripts/setup.py')
if ($Portable) { $setupArgs += '--portable' }
& '.\.venv\Scripts\python.exe' @setupArgs
if ($LASTEXITCODE) { throw 'Database setup failed.' }
Push-Location 'frontend'
try { & npm.cmd ci; if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' } } finally { Pop-Location }
Write-Host 'Setup complete. Start with .\start.ps1 -Build'
