param(
  [string]$HostName = "192.0.2.10",
  [int]$Port = 22,
  [string]$User = "nas-user",
  [string]$RemoteRoot = "/volume1/Saclay/projects",
  [string]$OutputPath = "tmp/nas_ssh_probe_prompt.json"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
if (!(Test-Path "tmp")) {
  New-Item -ItemType Directory -Path "tmp" | Out-Null
}

$secure = Read-Host "NAS SSH password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $env:FLUXIO_NAS_SSH_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  python scripts/nas_ssh_probe.py --host $HostName --port $Port --user $User --remote-root $RemoteRoot --diagnose |
    Tee-Object -FilePath $OutputPath
} finally {
  Remove-Item Env:\FLUXIO_NAS_SSH_PASSWORD -ErrorAction SilentlyContinue
  if ($bstr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}
