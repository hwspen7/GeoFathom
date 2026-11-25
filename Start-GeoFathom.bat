@echo off
setlocal
rem Run from the checkout root and preserve the real acceptance exit status.
pushd "%~dp0" || exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Local-Research.ps1" -Mode Start
set "result=%errorlevel%"
popd
if not "%result%"=="0" (
  echo.
  echo GeoFathom launch failed. Review the error above.
  if /i not "%~1"=="--no-pause" pause
  exit /b %result%
)
exit /b 0
