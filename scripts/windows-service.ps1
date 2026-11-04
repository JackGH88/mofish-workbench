param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('query','identity','install','start','enable','disable','uninstall')]
    [string]$Action,
    [string]$XmlPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
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
        Register-ScheduledTask -TaskPath '\' -TaskName $taskName -Xml $xml -Force | Out-Null
    }
    'start' { Start-ScheduledTask -TaskPath '\' -TaskName $taskName }
    'enable' { Enable-ScheduledTask -TaskPath '\' -TaskName $taskName | Out-Null }
    'disable' { Disable-ScheduledTask -TaskPath '\' -TaskName $taskName | Out-Null }
    'uninstall' { Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false }
}
