param([switch]$Relocate)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
else { throw 'Python 3 is required. Install Python and enable its PATH option first.' }
if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python virtual environment.' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; existing service registration was not changed.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$serviceArgs = @((Join-Path $PSScriptRoot 'scripts\service.py'), 'install')
if ($Relocate) { $serviceArgs += '--relocate' }
& $python @serviceArgs
exit $LASTEXITCODE
