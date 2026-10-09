@echo off
setlocal
set "TOOL_DIR=%~dp0"
set "PROJECT_ROOT=%TOOL_DIR%.."

python "%PROJECT_ROOT%\src\grant_agent\nas_transfer.py" %*
exit /b %errorlevel%
