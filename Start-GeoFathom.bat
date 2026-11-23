@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Local-Research.ps1" -Mode Start
if errorlevel 1 (
  echo.
  echo GeoFathom launch failed. Review the error above.
  pause
  exit /b 1
)
