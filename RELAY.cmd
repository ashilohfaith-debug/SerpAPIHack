@echo off
rem Start Relay from this folder (for a sighted helper). A blind user uses the
rem Ctrl+Alt+R desktop shortcut created by:  RELAY.cmd --install
cd /d "%~dp0"
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m relay --start
) else (
  ".venv\Scripts\python.exe" -m relay %*
)
