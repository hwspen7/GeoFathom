@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Local-Research.ps1" -Mode Quick
if errorlevel 1 (
  echo.
  echo Research acceptance FAILED. Preserve the log.
  pause
  exit /b 1
)
echo.
echo Focused research acceptance PASSED.
pause
