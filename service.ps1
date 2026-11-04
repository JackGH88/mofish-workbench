param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('start','stop','restart','status','enable','disable','uninstall')]
    [string]$Action
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run install.ps1 first.' }
& $python (Join-Path $PSScriptRoot 'scripts\service.py') $Action
exit $LASTEXITCODE
