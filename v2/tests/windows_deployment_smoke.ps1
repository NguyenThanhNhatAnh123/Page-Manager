# Hosted CI only. Exercises a real SYSTEM task update and a failed-start rollback.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Deployment integration runs only on disposable GitHub-hosted runners.'
}
$id = [Guid]::NewGuid().ToString('N')
$root = Join-Path $env:RUNNER_TEMP "pm-deployment-$id"
$initial = Join-Path $env:ProgramFiles "PageManager-CI-$id"
$cluster = Join-Path $root 'postgres'
$state = Join-Path $root 'state'
$config = Join-Path $state 'server.env'
$bundle = Join-Path (Get-Location) '.runtime\releases\PageManager-windows-x64.zip'
$checksum = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
$taskName = "PageManager-DeployCI-$id"
$python = (Get-Command python.exe).Source
$pgBin = $env:PGBIN
$taskCreated = $false
$databaseStarted = $false
New-Item -ItemType Directory -Path $root | Out-Null

function Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE) { throw "Deployment integration command failed: $([IO.Path]::GetFileName($Exe))" }
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
    throw 'CI deployment runtime did not become healthy.'
}
try {
    Checked (Join-Path $pgBin 'initdb.exe') @('-D',$cluster,'-U','postgres','-A','trust','--encoding=UTF8','--locale=C')
    Checked (Join-Path $pgBin 'pg_ctl.exe') @('-D',$cluster,'-l',(Join-Path $root 'postgres.log'),'-o','-h 127.0.0.1 -p 55433','-w','start')
    $databaseStarted = $true
    Checked (Join-Path $pgBin 'createdb.exe') @('-h','127.0.0.1','-p','55433','-U','postgres','native_deploy')
    $env:PM_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55433/native_deploy'
    Checked $python @('scripts/release_bundle.py','--bundle',$bundle,'--commit',$env:GITHUB_SHA,'--sha256',$checksum,'--destination',$initial)
    $app = Join-Path $initial 'v2'
    $appPython = Join-Path $app '.venv\Scripts\python.exe'
    Checked $python @('-m','venv',(Join-Path $app '.venv'))
    Checked $appPython @('-m','pip','install','--no-index','--find-links',(Join-Path $initial 'wheelhouse'),'-r',(Join-Path $app 'requirements-lock.txt'))
    $prepare = @'
import importlib.util, os, sys
from pathlib import Path
from dotenv import dotenv_values
app,state=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('native_config',app/'server/windows/configure.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
path=module.initialize(app,state)
values=dict(dotenv_values(path));values['DATABASE_URL']=os.environ['PM_TEST_DATABASE_URL'];values['PM_DEV_READ_ONLY']='1'
path.write_text(''.join(f'{k}={v}\n' for k,v in values.items()),encoding='utf-8')
'@
    Checked $python @('-c',$prepare,$app,$state)
    # Seed immutable history before starting any worker. The source is disconnected
    # and has no credentials, so the production worker cannot contact a provider.
    $seedHistory = @'
import os,sys
from pathlib import Path
from uuid import uuid4
from dotenv import dotenv_values
os.environ.update({k:v for k,v in dotenv_values(sys.argv[1]).items() if v is not None})
from scripts.provision import provision
provision(os.environ['DATABASE_URL'],Path(os.environ['PM_DATA_DIR'])/'initial-users.txt')
from worker.app import Registry,central
from tests.test_worker import connect,make_job
with central() as db:users=db.execute('SELECT id FROM public.pm_users ORDER BY id').fetchall()
registry=Registry()
for user in users:registry.get(user['id'])
workspace=registry.get(users[0]['id']);connect(workspace,'Disconnected deployment fixture')
job,_=make_job(workspace)
workspace.manager.store.reel_checkpoint(job['id'],{'finish_attempted':True,'finish_ack':True},status='completed',video_id='123456789',published_url='https://www.facebook.com/reel/123456789')
with workspace.manager.store.connect() as db:
    db.execute('UPDATE connections SET connected=0,encrypted_token=NULL')
    db.execute('UPDATE connection_pages SET active=0,encrypted_page_token=NULL')
with central() as db:
    db.execute("INSERT INTO pm_mcp_tokens(id,user_id,digest,label,expires_at) VALUES(%s,%s,%s,%s,now()+interval '30 days')",(uuid4().hex,users[0]['id'],'disposable-fixture-digest','Deployment fixture'))
'@
    Checked $python @('-c',$seedHistory,$config)
    $configHash = (Get-FileHash -LiteralPath $config).Hash
    Import-Module (Join-Path $app 'server\windows\Native-Tasks.psm1') -Force
    Register-PageManagerRuntime -PythonExe $appPython -RuntimeScript (Join-Path $app 'scripts\native_runtime.py') `
        -ConfigFile $config -GatewayExe (Join-Path $app 'bin\pagemanager-gateway.exe') -StateDirectory $state -AppRoot $app -TaskName $taskName
    $taskCreated = $true
    Start-PageManagerRuntime -StateDirectory $state -TaskName $taskName
    Wait-Healthy
    $deploy = Join-Path $app 'server\windows\Deploy-Release.ps1'
    & $deploy -Bundle $bundle -ExpectedCommit $env:GITHUB_SHA -ExpectedSha256 $checksum -StateDirectory $state -TaskName $taskName
    Wait-Healthy
    $healthyRelease = (Get-ScheduledTask -TaskPath '\PageManager\' -TaskName $taskName).Actions[0].WorkingDirectory
    if ($healthyRelease -eq $app) { throw 'Deployment did not switch the task to the new release.' }
    if ((Get-FileHash -LiteralPath $config).Hash -ne $configHash) { throw 'Deployment rewrote private configuration.' }

    # A validly checksummed fixture whose worker crashes only when started.
    $broken = Join-Path $root 'broken.zip'
    $inject = @'
import hashlib,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as original:
    files={name:original.read(name) for name in original.namelist()}
manifest=json.loads(files.pop('manifest.json'))
name='v2/worker/app.py';files[name]+=b'\nraise RuntimeError("CI injected startup failure")\n'
manifest['files'][name]={'bytes':len(files[name]),'sha256':hashlib.sha256(files[name]).hexdigest()}
with zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED) as output:
    for name,data in files.items():output.writestr(name,data)
    output.writestr('manifest.json',json.dumps(manifest))
'@
    Checked $python @('-c',$inject,$bundle,$broken)
    $brokenHash = (Get-FileHash -LiteralPath $broken -Algorithm SHA256).Hash.ToLowerInvariant()
    $rejected = $false
    try {
        & $deploy -Bundle $broken -ExpectedCommit $env:GITHUB_SHA -ExpectedSha256 $brokenHash `
            -StateDirectory $state -TaskName $taskName -HealthTimeoutSeconds 15
    } catch { $rejected = $true }
    if (!$rejected) { throw 'The injected worker failure was incorrectly accepted.' }
    Wait-Healthy
    $restored = (Get-ScheduledTask -TaskPath '\PageManager\' -TaskName $taskName).Actions[0].WorkingDirectory
    if ($restored -ne $healthyRelease) { throw 'Rollback did not restore the previous healthy task.' }
    if ((Get-FileHash -LiteralPath $config).Hash -ne $configHash) { throw 'Rollback rewrote private configuration.' }
    Write-Host 'Real SYSTEM deployment and failed-start rollback passed with configuration/read-only mode preserved.'
} finally {
    if ($taskCreated) {
        try { Stop-PageManagerRuntime -StateDirectory $state -TaskName $taskName } finally {
            Unregister-ScheduledTask -TaskPath '\PageManager\' -TaskName $taskName -Confirm:$false
        }
    }
    if ($databaseStarted) { & (Join-Path $pgBin 'pg_ctl.exe') -D $cluster -m fast -w stop }
    # All code/data directories belong to this disposable hosted VM and expire with it.
}
