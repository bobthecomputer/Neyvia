# Build with the existing local VS/SDK only; no installs or global changes.
param([switch]$ProbeOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$output = Join-Path $taskRoot '.agent_control/c11-parked'
$tools = Get-ChildItem 'C:/Program Files/Microsoft Visual Studio/18/Insiders/VC/Tools/MSVC' -Directory |
    Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = 'C:/Program Files (x86)/Windows Kits/10'
$sdkVersion = Get-ChildItem "$sdkRoot/Include" -Directory | Sort-Object Name -Descending | Select-Object -First 1
$compiler = Join-Path $tools.FullName 'bin/Hostx64/x64/cl.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Existing x64 Visual C++ compiler is required' }
$env:INCLUDE = "$($tools.FullName)/include;$sdkRoot/Include/$($sdkVersion.Name)/ucrt;$sdkRoot/Include/$($sdkVersion.Name)/shared;$sdkRoot/Include/$($sdkVersion.Name)/um"
$env:LIB = "$($tools.FullName)/lib/x64;$sdkRoot/Lib/$($sdkVersion.Name)/ucrt/x64;$sdkRoot/Lib/$($sdkVersion.Name)/um/x64"
New-Item -ItemType Directory -Path $output -Force | Out-Null
if (!$ProbeOnly) {
    $sourceHash = (Get-FileHash -LiteralPath "$taskRoot/tools/cua-driver-win/parked-hook.cpp" -Algorithm SHA256).Hash.ToLowerInvariant()
    $hookName = "parked-hook-$($sourceHash.Substring(0,16)).dll"
    & $compiler /nologo /LD /O2 /MT /EHsc "$taskRoot/tools/cua-driver-win/parked-hook.cpp" "/Fo$output/parked-hook.obj" "/Fe$output/$hookName" /link user32.lib kernel32.lib dwmapi.lib
    if ($LASTEXITCODE -ne 0) { throw 'Parked hook build failed' }
    @{file=$hookName; sourceSha256=$sourceHash; sha256=(Get-FileHash -LiteralPath "$output/$hookName" -Algorithm SHA256).Hash.ToLowerInvariant()} |
        ConvertTo-Json | Set-Content -LiteralPath "$output/parked-hook-build.json" -Encoding utf8
}
& $compiler /nologo /O2 /MT /EHsc "$taskRoot/tools/cua-driver-win/parked-probe.cpp" "/Fo$output/parked-probe.obj" "/Fe$output/parked-probe.exe" /link /SUBSYSTEM:WINDOWS user32.lib kernel32.lib ole32.lib uuid.lib dwmapi.lib shell32.lib
if ($LASTEXITCODE -ne 0) { throw 'Hidden probe build failed' }
