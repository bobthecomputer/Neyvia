[CmdletBinding()]
param(
    [string]$RuleName = "codex_sandbox_offline_block_outbound"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Result {
    param(
        [bool]$Ok,
        [string]$Stage,
        [string]$Message
    )
    [pscustomobject]@{
        ok = $Ok
        stage = $Stage
        ruleName = $RuleName
        message = $Message
    } | ConvertTo-Json -Compress
}

$rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if (-not $rule) {
    Write-Result -Ok $true -Stage "not_found" -Message "No matching Codex outbound block rule is present."
    exit 0
}

if (-not (Test-IsAdmin)) {
    $scriptPath = $PSCommandPath
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "`"$scriptPath`"",
        "-RuleName",
        "`"$RuleName`""
    ) -join " "
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs | Out-Null
    Write-Result -Ok $false -Stage "uac_requested" -Message "Administrator approval is required. A UAC prompt was opened to disable the local outbound block rule."
    exit 3010
}

Disable-NetFirewallRule -DisplayName $RuleName
$updated = Get-NetFirewallRule -DisplayName $RuleName
if ($updated.Enabled -eq "False") {
    Write-Result -Ok $true -Stage "disabled" -Message "Codex outbound block rule is disabled. Retry the NAS SSH probe."
    exit 0
}

Write-Result -Ok $false -Stage "still_enabled" -Message "The rule still appears enabled after the disable attempt."
exit 1
