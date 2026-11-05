param(
    [switch]$Relocate, [switch]$Check, [switch]$Resume,
    [switch]$RegisterOnly, [switch]$ChromeOnly, [switch]$SkipChrome
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location -LiteralPath $PSScriptRoot
$probe = 'import sys,struct,venv,ensurepip; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) and struct.calcsize("P")==8 else 1)'
function Test-Python([string]$Exe, [string[]]$PrefixArgs) {
    try {
        & $Exe @PrefixArgs -c $probe 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
$python = $null
$prefix = @()
$existing = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($null -ne (Get-Item -LiteralPath (Join-Path $PSScriptRoot '.venv') -Force -ErrorAction SilentlyContinue)) {
    if (-not (Test-Python $existing @())) {
        throw 'Existing .venv requires working Python 3.11/3.12 x64. Environment and data preserved; ask Agent to inspect before migration.'
    }
    $python = $existing
} else {
    $bootstrapArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'scripts\source-runtime.ps1'), '-Root', $PSScriptRoot)
    if ($Check) { $bootstrapArgs += '-Check' }
    $bootstrapHost = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $python = & $bootstrapHost @bootstrapArgs
    $bootstrapStatus = $LASTEXITCODE
    if ($bootstrapStatus -eq 0) {
        if (-not $python -or $python -is [array]) { throw 'Runtime bootstrap must return exactly one Python path.' }
    } elseif ($bootstrapStatus -eq 3 -or ($bootstrapStatus -eq 4 -and $Check)) {
        $python = $null
    } else { throw "Native runtime bootstrap failed (exit $bootstrapStatus)." }
    # py -3 may select an unsupported newer Python; select supported minors explicitly.
    if (-not $python -and (Get-Command py -ErrorAction SilentlyContinue)) {
        foreach ($version in @('-3.12', '-3.11')) {
            if (Test-Python 'py' @($version)) { $python = 'py'; $prefix = @($version); break }
        }
    }
    if (-not $python) {
        $candidates = @('python3.12', 'python3.11', 'python')
        foreach ($version in @('312', '311')) {
            $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe")
        }
        foreach ($candidate in $candidates) {
            if ((Get-Command $candidate -ErrorAction SilentlyContinue) -and (Test-Python $candidate @())) {
                $python = $candidate; break
            }
        }
    }
}
if (-not $python) {
    throw 'No usable Python 3.11/3.12 x64 (venv/pip). Store aliases and empty py launchers do not count. Ask Agent to prepare official Python per README, then rerun. https://www.python.org/downloads/windows/'
}
$installArgs = @((Join-Path $PSScriptRoot 'scripts\source_install.py'))
if ($Relocate) { $installArgs += '--relocate' }
if ($Check) { $installArgs += '--check' }
if ($Resume) { $installArgs += '--resume' }
if ($RegisterOnly) { $installArgs += '--register-only' }
if ($ChromeOnly) { $installArgs += '--chrome-only' }
if ($SkipChrome) { $installArgs += '--skip-chrome' }
& $python @prefix @installArgs
exit $LASTEXITCODE
