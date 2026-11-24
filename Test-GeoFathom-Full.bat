@echo off
setlocal
rem Run from the checkout root and preserve the real acceptance exit status.
pushd "%~dp0" || exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Local-Research.ps1" -Mode Full
set "result=%errorlevel%"
popd
if not "%result%"=="0" (
  echo.
  echo Full acceptance FAILED. Preserve the log and Playwright traces.
  if /i not "%~1"=="--no-pause" pause
  exit /b %result%
)
echo.
echo Full research acceptance PASSED.
if /i not "%~1"=="--no-pause" pause
exit /b 0
