[CmdletBinding()]
param(
    [string]$PythonExe = 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe',
    [int]$Port = 47881,
    [int]$PollSeconds = 5,
    # Overridable so the release swap can be tested beside the live supervisor.
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'Neyvia\controller-supervisor'),
    [string]$MutexName = 'Local\NeyviaRemoteControllerSupervisor'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$entry = Join-Path $root 'scripts\run_web_backend.py'
$logs = $StateDir
New-Item -ItemType Directory -Force -Path $logs | Out-Null
# Promotion writes release.json to serve a frozen release instead of this checkout.
$releasePointer = Join-Path $logs 'release.json'

# One supervisor per logon session. Task Scheduler is also configured IgnoreNew.
$mutex = [Threading.Mutex]::new($false, $MutexName)
if (-not $mutex.WaitOne(0)) { exit 0 }

function Write-SupervisorLog([string]$Message) {
    $line = '{0:o} {1}' -f [DateTimeOffset]::Now, $Message
    Add-Content -LiteralPath (Join-Path $logs 'supervisor.log') -Value $line -Encoding UTF8
}

function Get-PortOwners {
    @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-ExpectedBackendProcess([int]$ProcessId) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    $command = [string]$proc.CommandLine
    return ($command -match 'scripts[\\/]run_web_backend\.py' -and
        $command -match [regex]::Escape($root))
}

function Test-ControllerHealth {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3 -UseBasicParsing
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    } catch { return $false }
}

function Get-ReleaseLaunch {
    if (Test-Path -LiteralPath $releasePointer -PathType Leaf) {
        try {
            $release = Get-Content -LiteralPath $releasePointer -Raw -Encoding UTF8 | ConvertFrom-Json
            $releaseEntry = [string]$release.entry
            $staticRoot = [string]$release.staticRoot
            if ((Test-Path -LiteralPath $releaseEntry -PathType Leaf) -and (Test-Path -LiteralPath $staticRoot -PathType Container)) {
                return @{ Entry = $releaseEntry; StaticRoot = $staticRoot; Label = [string]$release.stamp }
            }
            Write-SupervisorLog "Release pointer names missing files; serving the workspace checkout instead."
        } catch {
            Write-SupervisorLog "Release pointer is unreadable ($($_.Exception.Message)); serving the workspace checkout instead."
        }
    }
    return @{ Entry = $entry; StaticRoot = ''; Label = 'workspace' }
}

function Get-BackendProcess {
    foreach ($owner in (Get-PortOwners)) {
        if (Test-ExpectedBackendProcess -ProcessId ([int]$owner)) {
            return Get-Process -Id ([int]$owner) -ErrorAction SilentlyContinue
        }
    }
    return $null
}

try {
    Write-SupervisorLog "Supervisor started for root=$root port=$Port."
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Configured Python executable is missing: $PythonExe"
    }
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
        throw "Backend entrypoint is missing: $entry"
    }

    while ($true) {
        $backend = Get-BackendProcess
        if (-not $backend -and (Test-ControllerHealth)) {
            # A healthy process owned by another launcher is already serving this
            # port. Leave it untouched; this supervisor checks again if it exits.
            Write-SupervisorLog 'A healthy controller is already serving the port; leaving its process untouched.'
            Start-Sleep -Seconds $PollSeconds
            continue
        }

        if (-not $backend) {
            $owners = @(Get-PortOwners)
            if ($owners.Count -gt 0) {
                Write-SupervisorLog "Port $Port is occupied by an unrelated process; waiting without terminating it."
                Start-Sleep -Seconds $PollSeconds
                continue
            }

            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $stdout = Join-Path $logs "backend-$stamp.out.log"
            $stderr = Join-Path $logs "backend-$stamp.err.log"
            Get-ChildItem -LiteralPath $logs -Filter 'backend-*.log' -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -Skip 20 |
                Remove-Item -Force -ErrorAction SilentlyContinue
            try {
                $launch = Get-ReleaseLaunch
                $arguments = '"{0}" --host 127.0.0.1 --port {1} --root "{2}" --skip-runtime-auto-update' -f $launch.Entry, $Port, $root
                if ($launch.StaticRoot) { $arguments += (' --static-root "{0}"' -f $launch.StaticRoot) }
                $backend = Start-Process -FilePath $PythonExe `
                    -ArgumentList $arguments `
                    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
                Write-SupervisorLog "Started backend process $($backend.Id) from $($launch.Label)."
            } catch {
                Write-SupervisorLog "Backend start failed: $($_.Exception.Message)"
                Start-Sleep -Seconds $PollSeconds
                continue
            }
        }

        # Do not run a second copy while the owned process is alive. If it exits,
        # the next iteration checks the port and restarts it when safe.
        while (-not $backend.HasExited) { Start-Sleep -Seconds $PollSeconds }
        Write-SupervisorLog "Backend process $($backend.Id) exited with code $($backend.ExitCode); checking for restart."
        Start-Sleep -Seconds 2
    }
} catch {
    Write-SupervisorLog "Supervisor stopped with error: $($_.Exception.Message)"
    throw
} finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
}
