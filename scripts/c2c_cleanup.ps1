param([Parameter(Mandatory=$true)][int]$BackendPort,[Parameter(Mandatory=$true)][int]$ControlPort)
$ErrorActionPreference='Stop'
if ($BackendPort -ne 48721 -or $ControlPort -ne 48722) { throw 'Only original owned C2c ports 48721/48722' }
$ownedProcesses=@()
foreach ($taskPort in @($BackendPort,$ControlPort)) {
    $listener=Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue
    if (!$listener) { throw "Expected owned listener absent: $taskPort" }
    $taskProcessId=($listener | Select-Object -First 1).OwningProcess
    $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
    if ($taskPort -eq $BackendPort -and ($taskProcess.CommandLine -notmatch 'run_web_backend.py' -or $taskProcess.CommandLine -notmatch 'bea453a3-8823-462d-a857-b043e2d733a6')) { throw 'Backend ownership mismatch' }
    if ($taskPort -eq $ControlPort -and $taskProcess.CommandLine -notmatch 'c2c_webvoyager.cjs') { throw 'Coordinator ownership mismatch' }
    $ownedProcesses+=@{port=$taskPort;pid=$taskProcessId}
}
$base="http://127.0.0.1:$BackendPort"
$null=Invoke-WebRequest -Uri "$base/api/auth/local-session" -Method Post -ContentType 'application/json' -Body '{}' -SessionVariable c2cCleanupSession
$headless=Invoke-RestMethod -Uri "$base/api/ui/browser" -Method Post -ContentType 'application/json' -Body '{"op":"headless.stop","args":{}}' -WebSession $c2cCleanupSession
if (!$headless.ok) { throw 'Owned headless stop failed' }
foreach ($owned in $ownedProcesses) { Stop-Process -Id $owned.pid }
$remaining=@(48721,48722,48723,48724,48725,48726,48727,48728 | ForEach-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
if ($remaining.Count) { throw 'Owned task listeners remain' }
$receipt=@{schema='neyvia.C2c.cleanup@1';at=[DateTime]::UtcNow.ToString('o');owned=$ownedProcesses;headlessStop=$headless;ports48721Through48728Clear=$true;unrelated48729Untouched=$true}
$receipt | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath scripts/evidence/C2c-browser-cleanup.json
Write-Output 'Owned C2c browser services stopped; ports 48721-48728 clear.'
