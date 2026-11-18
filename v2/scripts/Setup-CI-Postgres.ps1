# Disposable GitHub-hosted runner only; never installs a Windows service.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'PostgreSQL CI bootstrap is restricted to GitHub-hosted runners.'
}
$archive = Join-Path $env:RUNNER_TEMP 'postgresql-18.7.zip'
$destination = Join-Path $env:RUNNER_TEMP 'postgresql-18.7'
Invoke-WebRequest 'https://get.enterprisedb.com/postgresql/postgresql-18.7-1-windows-x64-binaries.zip' -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne 'EAD0BBC27FB678FA24DCF86B738981323042ABD073C744103BF7F3AED23F9A33') {
    throw 'Official PostgreSQL archive checksum mismatch.'
}
Expand-Archive -LiteralPath $archive -DestinationPath $destination
$bin = Join-Path $destination 'pgsql\bin'
$version = & (Join-Path $bin 'postgres.exe') --version
if ($LASTEXITCODE -or $version -notmatch 'PostgreSQL\) 18\.') { throw 'PostgreSQL major 18 required.' }
"PGBIN=$bin" | Out-File -LiteralPath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host $version
