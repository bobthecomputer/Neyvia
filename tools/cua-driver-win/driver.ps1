param([Parameter(Mandatory=$true)][string]$AssemblyPath)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    [System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = 'Normal'
    $framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\WPF'
    [void][System.Reflection.Assembly]::LoadFrom((Join-Path $framework 'UIAutomationClient.dll'))
    [void][System.Reflection.Assembly]::LoadFrom((Join-Path $framework 'UIAutomationTypes.dll'))
    [void][System.Reflection.Assembly]::LoadFrom((Join-Path $framework 'WindowsBase.dll'))
    Add-Type -Path $AssemblyPath
    [T16.NativeWorker]::StartHooks()
} catch {
    [Console]::Error.WriteLine('Native worker initialization failed: ' + $_.Exception.Message)
    exit 1
}
while ($null -ne ($line = [Console]::ReadLine())) {
    $id = $null
    try {
        $request = $line | ConvertFrom-Json
        $id = $request.id
        $a = $request.args
        switch ($request.op) {
            'windows' { $data = [T16.NativeWorker]::Windows() }
            'window' { $data = [T16.NativeWorker]::WindowMetadata([string]$a.windowId) }
            'status' { $data = [T16.NativeWorker]::Status() }
            'inspect' {
                $depth = 8; $nodes = 500
                if ($null -ne $a.maxDepth) { $depth = [int]$a.maxDepth }
                if ($null -ne $a.maxNodes) { $nodes = [int]$a.maxNodes }
                $data = [T16.NativeWorker]::Inspect([string]$a.windowId, $depth, $nodes)
            }
            'remoteGuard' { $data = [T16.NativeWorker]::RemoteGuard([string]$a.windowId) }
            'remoteObserve' { $data = [T16.NativeWorker]::RemoteObserve([string]$a.windowId, [bool]$a.image) }
            'remoteAction' {
                $data = [T16.NativeWorker]::RemoteAction([string]$a.windowId,[string]$a.elementId,[string]$a.action,[string]$a.text,[string]$a.horizontal,[string]$a.vertical,[string]$a.x,[string]$a.y,[string]$a.key,[string]$a.expectedName,[string]$a.expectedRole,[string]$a.expectedClass,[long]$a.inputGeneration)
            }
            'capture' { $data = [T16.NativeWorker]::Capture([string]$a.windowId) }
            'action' {
                $data = [T16.NativeWorker]::Action([string]$a.windowId, [string]$a.elementId, [string]$a.action,
                    [string]$a.text, [string]$a.value, [string]$a.horizontal, [string]$a.vertical,
                    [string]$a.x, [string]$a.y, [string]$a.key)
            }
            default { throw 'Unknown operation' }
        }
        $response = @{id=$id; ok=$true; data=$data}
    } catch {
        $message = $_.Exception.Message
        if ($null -ne $_.Exception.InnerException) { $message = $_.Exception.InnerException.Message }
        $response = @{id=$id; ok=$false; error=$message}
    }
    [Console]::WriteLine(($response | ConvertTo-Json -Depth 40 -Compress))
}
