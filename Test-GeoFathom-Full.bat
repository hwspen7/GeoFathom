@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Local-Research.ps1" -Mode Full
if errorlevel 1 (
  echo.
  echo Full acceptance FAILED. Preserve the log and Playwright traces.
  pause
  exit /b 1
)
echo.
echo Full research acceptance PASSED.
pause
