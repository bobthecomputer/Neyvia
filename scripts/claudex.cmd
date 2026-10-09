@echo off
REM claudex.cmd — Claude Code via CLIProxyAPI -> ChatGPT/Codex (no `claude auth login`)
setlocal EnableExtensions

set "ROOT=%~dp0.."
set "ENVFILE=%ROOT%\.agent_control\cliproxy_local.env"
if exist "%ENVFILE%" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENVFILE%") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if "%CLIPROXY_PORT%"=="" set "CLIPROXY_PORT=8317"
if "%ANTHROPIC_BASE_URL%"=="" set "ANTHROPIC_BASE_URL=http://127.0.0.1:%CLIPROXY_PORT%"
if not "%CLIPROXY_API_KEY%"=="" if "%ANTHROPIC_AUTH_TOKEN%"=="" set "ANTHROPIC_AUTH_TOKEN=%CLIPROXY_API_KEY%"
if "%CLAUDE_CODE_SUBAGENT_MODEL%"=="" set "CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol"
if "%CLAUDE_CODE_ALWAYS_ENABLE_EFFORT%"=="" set "CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1"
if "%CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY%"=="" set "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1"
if "%FLUXIO_HARNESS_COMPAT%"=="" set "FLUXIO_HARNESS_COMPAT=cliproxy"

where claude >nul 2>nul
if errorlevel 1 (
  echo claude CLI not found on PATH. Install @anthropic-ai/claude-code first.
  exit /b 1
)

claude --model gpt-5.6-sol %*
