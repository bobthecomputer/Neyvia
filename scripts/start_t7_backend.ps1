$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:NEYVIA_COORDINATOR_AUTOSTART='0'
$env:FLUXIO_WATCHDOG_AUTOSTART='0'
$env:NEYVIA_CONNECTED_SERVICE_PORT='48211'
$env:NEYVIA_SIDEBAR_ALLOWED_ROOTS=ConvertTo-Json -InputObject @('C:\Users\user\Projects\nx-t7-sidebar') -Compress
$env:NEYVIA_SIDEBAR_EXCLUDED_ROOTS=ConvertTo-Json -InputObject @('C:\Users\user\Projects\Neyvia','C:\Users\user\Projects\Neyvia-next') -Compress
& 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe' scripts/run_web_backend.py --host 127.0.0.1 --port 48211 --root .agent_control/t7/runtime --skip-runtime-auto-update
