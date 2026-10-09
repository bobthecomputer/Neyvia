# claudex.ps1 — PowerShell equivalent of Tibo's claudex alias (Windows)
# Usage:
#   . .\scripts\claudex.ps1          # define function in current session
#   claudex                          # launch Claude Code via CLIProxyAPI
#   claudex -p "hello"               # pass args through to claude

function Import-ClaudexEnv {
    param([string]$EnvFile)
    if (-not (Test-Path -LiteralPath $EnvFile)) { return }
    Get-Content -LiteralPath $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $parts = $line.Split('=', 2)
        if ($parts.Count -ne 2) { return }
        Set-Item -Path "Env:$($parts[0].Trim())" -Value $parts[1].Trim()
    }
}

function Invoke-Claudex {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$ClaudeArgs
    )

    $root = Split-Path -Parent $PSScriptRoot
    if (-not $root) { $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }
    Import-ClaudexEnv (Join-Path $root '.agent_control\cliproxy_local.env')

    if (-not $env:CLIPROXY_PORT) { $env:CLIPROXY_PORT = '8317' }
    if (-not $env:ANTHROPIC_BASE_URL) {
        $env:ANTHROPIC_BASE_URL = "http://127.0.0.1:$($env:CLIPROXY_PORT)"
    }
    if ($env:CLIPROXY_API_KEY -and -not $env:ANTHROPIC_AUTH_TOKEN) {
        $env:ANTHROPIC_AUTH_TOKEN = $env:CLIPROXY_API_KEY
    }
    if (-not $env:CLAUDE_CODE_SUBAGENT_MODEL) { $env:CLAUDE_CODE_SUBAGENT_MODEL = 'gpt-5.6-sol' }
    if (-not $env:CLAUDE_CODE_ALWAYS_ENABLE_EFFORT) { $env:CLAUDE_CODE_ALWAYS_ENABLE_EFFORT = '1' }
    if (-not $env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY) {
        $env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = '1'
    }
    if (-not $env:FLUXIO_HARNESS_COMPAT) { $env:FLUXIO_HARNESS_COMPAT = 'cliproxy' }

    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $claude) {
        throw "claude CLI not found on PATH. Install @anthropic-ai/claude-code first."
    }

    & $claude.Source --model gpt-5.6-sol @ClaudeArgs
}

Set-Alias -Name claudex -Value Invoke-Claudex -Scope Global -Force
Write-Host "Defined claudex -> ANTHROPIC_BASE_URL + Claude Code (proxy-backed). Plain 'claude' unchanged."
