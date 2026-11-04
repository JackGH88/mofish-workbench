$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'service.ps1') restart
exit $LASTEXITCODE
