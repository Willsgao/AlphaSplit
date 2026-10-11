@echo off
setlocal
cd /d "%~dp0"
title AlphaSplit Launcher
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
  echo.
  echo AlphaSplit failed to start. See the error message above.
  pause
)
endlocal
