param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('query','identity','install','start','enable','disable','uninstall')]
    [string]$Action,
    [string]$XmlPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$taskName = "VideoWorkbench-$sid"
$task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
switch ($Action) {
    'identity' { @{sid=$sid} | ConvertTo-Json -Compress }
    'query' {
        if ($null -eq $task) { @{registered=$false} | ConvertTo-Json -Compress }
        else { @{registered=$true; enabled=[bool]$task.Settings.Enabled; description=$task.Description} | ConvertTo-Json -Compress }
    }
    'install' {
        $xml = [System.IO.File]::ReadAllText($XmlPath, [System.Text.Encoding]::UTF8)
        try {
            Register-ScheduledTask -TaskPath '\' -TaskName $taskName -Xml $xml -Force | Out-Null
        } catch {
            # ASCII JSON survives legacy Windows PowerShell encodings; Python renders Chinese.
            $nativeCode = if ($_.Exception.PSObject.Properties['ErrorCode']) { $_.Exception.ErrorCode } else { $_.Exception.HResult }
            @{ ok=$false; action='install'; errorCode=('0x{0:X8}' -f ($nativeCode -band 0xffffffffL)); category=$_.CategoryInfo.Category.ToString() } | ConvertTo-Json -Compress
            exit 1
        }
    }
    'start' { Start-ScheduledTask -TaskPath '\' -TaskName $taskName }
    'enable' { Enable-ScheduledTask -TaskPath '\' -TaskName $taskName | Out-Null }
    'disable' { Disable-ScheduledTask -TaskPath '\' -TaskName $taskName | Out-Null }
    'uninstall' { Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false }
}
