# Fetch the maintained MIT DLL into this task only; no installation or switches.
$ErrorActionPreference = 'Stop'
$area = Join-Path (Split-Path -Parent $PSScriptRoot) '.agent_control/c11-bureau'
$release = '2024-12-16-windows11'
$expected = '8740c572a1c000e3b87ffeb1e4c397eae9af3bd4a2abdc3bcffacab4493f8ff5'
$metadata = Invoke-RestMethod "https://api.github.com/repos/Ciantic/VirtualDesktopAccessor/releases/tags/$release"
$asset = $metadata.assets | Where-Object name -eq 'VirtualDesktopAccessor.dll'
if (!$asset -or $asset.size -gt 209715200) { throw 'Missing or oversized VirtualDesktopAccessor asset' }
New-Item -ItemType Directory -Path $area -Force | Out-Null
$dllPath = Join-Path $area 'VirtualDesktopAccessor.dll'
if (!(Test-Path -LiteralPath $dllPath)) { Invoke-WebRequest $asset.browser_download_url -OutFile $dllPath }
if ((Get-FileHash -LiteralPath $dllPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'VirtualDesktopAccessor differs from the pinned release'
}
Invoke-WebRequest "https://raw.githubusercontent.com/Ciantic/VirtualDesktopAccessor/$release/LICENSE.txt" -OutFile (Join-Path $area 'LICENSE.txt')
Write-Output "Task-local MIT VirtualDesktopAccessor ready: $($asset.size) bytes"
