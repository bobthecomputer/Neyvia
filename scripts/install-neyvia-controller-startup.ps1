[CmdletBinding()]
param(
    [switch]$StartNow,
    [string]$TaskName = 'Neyvia Remote Controller Backend'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$supervisor = Join-Path $root 'scripts\start-neyvia-controller.ps1'
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue

if ($existing) {
    $ownedAction = $false
    foreach ($action in $existing.Actions) {
        if ([string]$action.Arguments -like "*$supervisor*") { $ownedAction = $true }
    }
    if (-not $ownedAction) {
        throw "Task '$TaskName' already exists with a different action; it was left unchanged."
    }
}

$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) {
    throw 'Windows PowerShell is unavailable; the controller task was not changed.'
}
$arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $supervisor
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description 'Keeps the Neyvia Tailscale controller backend available after this user signs in.' `
    -Force | Out-Null

if ($StartNow) { Start-ScheduledTask -TaskName $TaskName -TaskPath '\' }

$registered = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
[pscustomobject]@{
    taskName = $TaskName
    state = $registered.State.ToString()
    user = $currentUser
    trigger = 'At this user logon'
    action = $registered.Actions[0].Execute
    supervisor = $supervisor
    startedNow = [bool]$StartNow
    existingPhoneTaskPreserved = [bool](Get-ScheduledTask -TaskName 'Neyvia Phone PWA Backend' -ErrorAction SilentlyContinue)
} | ConvertTo-Json -Depth 4
