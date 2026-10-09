# Isolated agent-view proof backend on 48901, started with a hidden console so that
# console children (codex app-server, dictation engine) inherit it and never show a window.
$env:PYTHONPATH = "src"
$env:NEYVIA_OBSCURA_EXE = "C:/Users/user/Projects/nx-c13-taste/scripts/evidence/c13-runtime/obscura-v0.2.4/obscura.exe"
$env:NEYVIA_BROWSER_PROOF_PORTS = "48903,48904"
$env:NEYVIA_PROOF_ALLOWED_PORTS = "[48903,48904]"
$env:NEYVIA_COORDINATOR_AUTOSTART = "0"; $env:NEYVIA_TOOL_AUTO_UPDATE = "0"; $env:FLUXIO_WATCHDOG_AUTOSTART = "0"; $env:FLUXIO_RUNTIME_AUTO_UPDATE = "0"
$log = "C:/Users/user/Projects/nx-agentview/.agent_control/agentview/backend.log"
$p = Start-Process -FilePath "C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe" -WorkingDirectory "C:\Users\user\Projects\nx-agentview" `
  -ArgumentList "scripts/run_web_backend.py","--host","127.0.0.1","--port","48901","--root","C:/Users/user/Projects/nx-agentview","--static-root","C:/Users/user/Projects/nx-agentview/web/dist","--skip-runtime-auto-update","--skip-proof-self-check" `
  -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
$p.Id | Out-File -Encoding ascii "C:/Users/user/Projects/nx-agentview/.agent_control/agentview/backend.pid"
"started $($p.Id)"
