# Windows PowerShell 5.1, OS/.NET only. stdout is a single Python path.
# Exit 3: platform has no release; exit 4: check requires an installed Python.
param([string]$Root = (Split-Path -Parent $PSScriptRoot), [switch]$Check)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-StrictMode -Version 2
$stage = $null
function Progress-Message([string]$Text) { [Console]::Error.WriteLine($Text) }
function Assert-NoLinks([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Cache path contains reparse point: $Path" }
        if ($item -is [IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
    }
}
function Assert-Space([string]$Path, [long]$Bytes) {
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Path))
    if ($drive.AvailableFreeSpace -lt ($Bytes + 67108864)) { throw 'Insufficient runtime cache disk space.' }
}
function Test-Archive([string]$Path, $Entry) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    Assert-NoLinks $Path
    return ((Get-Item -LiteralPath $Path).Length -eq $Entry.bytes -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Entry.sha256)
}
function Assert-Https([string]$Url) {
    $uri = [Uri]$Url
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -cne 'https' -or -not $uri.Host -or $uri.UserInfo -or $uri.Fragment) { throw 'Runtime mirror/redirect must be HTTPS without credentials or fragments.' }
    return $uri
}
function Download-Bundle($Entry, [string]$Path) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $deadline = [DateTime]::UtcNow.AddSeconds(900)
    $last = 'No successful mirror'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        foreach ($url in $Entry.urls) {
            if ([DateTime]::UtcNow -ge $deadline) { throw 'Runtime download exceeded 900-second budget.' }
            Progress-Message "Runtime download attempt $attempt/3"
            $response = $null; $inputStream = $null; $output = $null
            try {
                $uri = Assert-Https $url
                for ($redirect = 0; $redirect -le 5; $redirect++) {
                    $request = [Net.HttpWebRequest]::Create($uri)
                    $request.AllowAutoRedirect = $false
                    $request.Timeout = [int][Math]::Max(1, [Math]::Min(30000, ($deadline - [DateTime]::UtcNow).TotalMilliseconds))
                    $request.ReadWriteTimeout = $request.Timeout
                    $request.Headers['Accept-Encoding'] = 'identity'
                    $response = $request.GetResponse()
                    $status = [int]$response.StatusCode
                    if ($status -ge 300 -and $status -lt 400) {
                        $location = $response.Headers['Location']
                        $response.Close(); $response = $null
                        if (-not $location -or $redirect -eq 5) { throw 'Invalid/excessive runtime redirect.' }
                        $uri = Assert-Https ([Uri]::new($uri, $location).AbsoluteUri)
                        continue
                    }
                    if ($status -ne 200 -or ($response.ContentEncoding -and $response.ContentEncoding -ne 'identity')) { throw 'Unexpected runtime HTTP response.' }
                    break
                }
                if ($response.ContentLength -gt $Entry.bytes) { throw 'Runtime download exceeds declared size.' }
                $inputStream = $response.GetResponseStream()
                $output = [IO.File]::Open($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
                $buffer = New-Object byte[] 1048576
                [long]$count = 0
                while (($n = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $count += $n
                    if ($count -gt $Entry.bytes -or [DateTime]::UtcNow -ge $deadline) { throw 'Runtime download exceeds size/time limit.' }
                    $output.Write($buffer, 0, $n)
                }
                $output.Dispose(); $output = $null
                if ($count -ne $Entry.bytes -or -not (Test-Archive $Path $Entry)) { throw 'Runtime SHA/size mismatch.' }
                return
            } catch { $last = $_.Exception.Message }
            finally {
                if ($null -ne $output) { $output.Dispose() }
                if ($null -ne $inputStream) { $inputStream.Dispose() }
                if ($null -ne $response) { $response.Close() }
            }
        }
    }
    throw "Runtime download failed verification: $last"
}
function Expand-SafeZip([string]$Archive, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -gt 100000) { throw 'Too many ZIP entries.' }
        $seen = @{}; $paths = @{}; [long]$total = 0
        # Validate the entire directory before creating any output files.
        foreach ($member in $zip.Entries) {
            $name = $member.FullName
            $directory = $name.EndsWith('/')
            $clean = $name.TrimEnd('/')
            if (-not $clean -or $name -match '[\\:*?"<>|\x00-\x1f\x7f]' -or $name.StartsWith('/') -or $name.EndsWith('//')) { throw 'Unsafe archive path.' }
            $parts = $clean.Split('/')
            foreach ($part in $parts) {
                if (-not $part -or $part -eq '.' -or $part -eq '..' -or $part -match '[ .]$' -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$') { throw 'Unsafe archive path.' }
            }
            if ($seen.ContainsKey($clean)) { throw 'Duplicate case-insensitive archive path.' }
            $seen[$clean] = $true
            for ($i = 1; $i -le $parts.Length; $i++) {
                $path = ($parts[0..($i-1)] -join '/')
                $kind = if ($i -lt $parts.Length -or $directory) { 'dir' } else { 'file' }
                if ($paths.ContainsKey($path) -and ($paths[$path].Name -cne $path -or $paths[$path].Kind -ne $kind)) { throw 'Conflicting archive paths.' }
                $paths[$path] = @{Name=$path; Kind=$kind}
            }
            $mode = ($member.ExternalAttributes -shr 16) -band 65535
            $type = $mode -band 61440
            $expected = if ($directory) { 16384 } else { 32768 }
            if (($type -ne 0 -and $type -ne $expected) -or ($member.ExternalAttributes -band 1024)) { throw 'Archive links/special files forbidden.' }
            $total += $member.Length
            if ($member.Length -lt 0 -or $total -gt 6442450944 -or ($directory -and $member.Length -ne 0)) { throw 'Archive expansion exceeds limit.' }
        }
        Assert-Space (Split-Path -Parent $Destination) $total
        if (Test-Path -LiteralPath $Destination) { throw 'Extraction destination must be new.' }
        [void][IO.Directory]::CreateDirectory($Destination)
        $buffer = New-Object byte[] 1048576
        $deadline = [DateTime]::UtcNow.AddSeconds(600)
        foreach ($member in $zip.Entries) {
            $target = Join-Path $Destination $member.FullName.Replace('/', '\')
            if ($member.FullName.EndsWith('/')) { [void][IO.Directory]::CreateDirectory($target); continue }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
            $inputStream = $null; $output = $null
            try {
                $inputStream = $member.Open()
                $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                [long]$count = 0
                while (($n = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $count += $n
                    if ($count -gt $member.Length -or [DateTime]::UtcNow -gt $deadline) { throw 'ZIP member exceeds size/time bound.' }
                    $output.Write($buffer, 0, $n)
                }
                if ($count -ne $member.Length) { throw 'Truncated ZIP member.' }
            } finally {
                if ($null -ne $inputStream) { $inputStream.Dispose() }
                if ($null -ne $output) { $output.Dispose() }
            }
        }
    } finally { $zip.Dispose() }
}
try {
    if ($env:OS -ne 'Windows_NT' -or ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64')) { throw 'Native runtime requires Windows x64.' }
    $Root = (Resolve-Path -LiteralPath $Root).Path
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'distribution\source-runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schemaVersion -ne 1 -or $null -eq $manifest.platforms -or $manifest.platforms -isnot [PSCustomObject]) { throw 'Unsupported runtime manifest.' }
    $property = $manifest.platforms.PSObject.Properties['windows-x64']
    if ($null -eq $property) { exit 3 }
    $entry = $property.Value
    if ($null -eq $entry -or $entry.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $entry.requirementsSha256 -cnotmatch '^[a-f0-9]{64}$' -or ($entry.bytes -isnot [int] -and $entry.bytes -isnot [long]) -or $entry.bytes -le 0 -or $entry.bytes -gt 2147483648 -or $entry.urls -isnot [array] -or $entry.urls.Count -lt 1 -or $entry.urls.Count -gt 4) { throw 'Invalid runtime entry.' }
    foreach ($url in $entry.urls) { if ($url -isnot [string]) { throw 'Invalid mirror.' }; $null = Assert-Https $url }
    if ((Get-FileHash -LiteralPath (Join-Path $Root 'requirements.txt') -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.requirementsSha256) { throw 'Runtime requirements fingerprint mismatch.' }
    if ($Check) { Progress-Message 'Check requires an installed Python/venv. Run install.ps1 without -Check to bootstrap the published runtime.'; exit 4 }
    $base = $env:LOCALAPPDATA
    if (-not $base) { $base = Join-Path $env:USERPROFILE 'AppData\Local' }
    $cache = [IO.Path]::GetFullPath((Join-Path $base 'Mofish\source-runtime'))
    if (($cache.TrimEnd('\') + '\').StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Runtime cache must be outside repository.' }
    [void][IO.Directory]::CreateDirectory($cache)
    Assert-NoLinks $cache
    foreach ($name in @('archives', 'bootstrap')) { $dir = Join-Path $cache $name; [void][IO.Directory]::CreateDirectory($dir); Assert-NoLinks $dir }
    # Keep temporary paths below legacy Win32 limits; the archive filename and
    # subsequent official runtime seal already bind this stage to its full SHA.
    $stage = Join-Path $cache ('bootstrap\' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    $archive = Join-Path $cache ('archives\' + $entry.sha256 + '.bundle')
    if (-not (Test-Archive $archive $entry)) {
        if (Test-Path -LiteralPath $archive) { throw 'Invalid cached bundle preserved; remove it explicitly and retry.' }
        Assert-Space $cache $entry.bytes
        $download = Join-Path $stage 'download'
        Download-Bundle $entry $download
        # No overwrite; concurrent bootstrap may have published the same archive.
        try { [IO.File]::Move($download, $archive) } catch { if (-not (Test-Archive $archive $entry)) { throw } }
    }
    Progress-Message 'Extracting verified bootstrap runtime...'
    $runtime = Join-Path $stage 'runtime'
    Expand-SafeZip $archive $runtime
    $python = Join-Path $runtime 'python\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Bundle missing Python.' }
    & $python -I -B -X utf8 -c 'import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from scripts.source_runtime import prepare_runtime,python_path; r=prepare_runtime(Path(sys.argv[1])); assert r is not None; print(python_path(r))' $Root
    if ($LASTEXITCODE -ne 0) { throw 'Bundled Python failed to prepare verified runtime.' }
} catch { Progress-Message $_.Exception.Message; exit 1 }
finally { if ($null -ne $stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force } }
