<#
Local-first Windows research workflow.
Start launches isolated consoles; Quick checks core GIS/Terrain workflows;
Full validates native MSVC, all Python, all web and serial/concurrent Chromium.
#>
[CmdletBinding()]
param([ValidateSet('Start','Quick','Full')][string]$Mode='Start')
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$web=Join-Path $root 'web'
$venv=Join-Path $root '.venv\Scripts\python.exe'
Set-Location -LiteralPath $root

function CommandPath([string]$name) {
    $cmd=Get-Command $name -ErrorAction SilentlyContinue
    if(-not $cmd){throw "Missing prerequisite: $name. Install it and reopen PowerShell."}
    return $cmd.Source
}
function Checked([string]$exe,[string[]]$arguments,[string]$label) {
    Write-Host ''
    Write-Host "==> $label" -ForegroundColor Cyan
    # Display native output without returning it as a PowerShell function
    # result; Ensure-Node must return only the npm executable path.
    & $exe @arguments | Out-Host
    if($LASTEXITCODE -ne 0){throw "$label failed (exit $LASTEXITCODE)"}
}
function Ensure-Python {
    if(-not (Test-Path -LiteralPath $venv)){
        $system=CommandPath 'python.exe'
        Checked $system @('-m','venv',(Join-Path $root '.venv')) 'Create isolated Python environment'
    }
    Checked $venv @('-c','import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"') 'Check Python version'
    $depsReady=$false
    try {
        & $venv -c 'import fastapi, rasterio, pyproj, shapely, uvicorn, pytest' 2>$null | Out-Null
        $depsReady=($LASTEXITCODE -eq 0)
    } catch {
        $depsReady=$false
    }
    if(-not $depsReady){
        Checked $venv @('-m','pip','install','-c','requirements/windows.lock','-e','.[dev]') 'Install locked Windows GIS dependencies'
    }
}
function Ensure-Node {
    $null=CommandPath 'node.exe'
    $npm=CommandPath 'npm.cmd'
    if($Mode -ne 'Start' -or -not (Test-Path -LiteralPath (Join-Path $web 'node_modules\.bin\vite.cmd'))){
        Push-Location -LiteralPath $web
        try{Checked $npm @('ci','--no-audit','--no-fund') 'Restore pinned frontend dependencies'}
        finally{Pop-Location}
    }
    return $npm
}
function Port-Occupied([int]$port){
    $socket=New-Object System.Net.Sockets.TcpClient
    try{
        $pending=$socket.BeginConnect('127.0.0.1',$port,$null,$null)
        if(-not $pending.AsyncWaitHandle.WaitOne(350)){return $false}
        $socket.EndConnect($pending)
        return $true
    }catch{return $false}finally{$socket.Close()}
}
function Require-FreePorts {
    foreach($port in @(8000,5173)){
        if(Port-Occupied $port){
            throw "Port $port is occupied. Close earlier GeoFathom server windows. The test runner must never reuse a live project."
        }
    }
}
function Http-Ready([string]$url) {
    try{
        $response=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }catch{return $false}
}
function Quote-PS([string]$value){return "'" + $value.Replace("'","''") + "'"}
function Launch-Window([string]$title,[string]$workingDir,[string]$exe,[string[]]$arguments){
    $argsQuoted=(@($arguments | ForEach-Object {Quote-PS $_}) -join ' ')
    $command='$Host.UI.RawUI.WindowTitle='+(Quote-PS $title)+
        '; Set-Location -LiteralPath '+(Quote-PS $workingDir)+
        '; & '+(Quote-PS $exe)+' '+$argsQuoted+
        '; Write-Host "Server stopped. Close this console when finished."'
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $workingDir -ArgumentList @(
        '-NoLogo','-NoProfile','-NoExit','-EncodedCommand',$encoded
    ) | Out-Null
}

Write-Host "GeoFathom Windows research: $Mode" -ForegroundColor Cyan
Ensure-Python
$npm=Ensure-Node

if($Mode -eq 'Start'){
    Require-FreePorts
    # This launcher binds to loopback only. Keep any model-admin token intact.
    # An explicit process override (including 0) is respected.
    $previousRasterImport=$env:GEOFATHOM_LOCAL_RASTER_IMPORT
    try{
        if($null -eq $previousRasterImport){$env:GEOFATHOM_LOCAL_RASTER_IMPORT='1'}
        Launch-Window 'GeoFathom API (8000)' $root $venv @(
            '-m','uvicorn','core.main:app','--host','127.0.0.1','--port','8000'
        )
    }finally{
        if($null -eq $previousRasterImport){Remove-Item Env:\GEOFATHOM_LOCAL_RASTER_IMPORT -ErrorAction SilentlyContinue}
        else{$env:GEOFATHOM_LOCAL_RASTER_IMPORT=$previousRasterImport}
    }
    # Wait for the API before exposing the frontend to existing browser tabs.
    Write-Host 'Waiting for GeoFathom API readiness...' -ForegroundColor Cyan
    $ready=$false
    for($i=0;$i -lt 80;$i++){
        if(Http-Ready 'http://127.0.0.1:8000/health/ready'){
            $ready=$true;break
        }
        Start-Sleep -Milliseconds 750
    }
    if(-not $ready){
        throw 'API not ready on port 8000. Inspect the GeoFathom API console for the startup error. The frontend was not started; no stored projects were deleted.'
    }
    Launch-Window 'GeoFathom Web (5173)' $web $npm @(
        'run','dev','--','--host','127.0.0.1','--port','5173','--strictPort'
    )
    # Verify the actual Vite proxy path, not just the frontend HTML response.
    $ready=$false
    for($i=0;$i -lt 80;$i++){
        if(Http-Ready 'http://127.0.0.1:5173/api/health/ready'){
            $ready=$true;break
        }
        Start-Sleep -Milliseconds 750
    }
    if(-not $ready){
        throw 'Frontend API proxy not ready. Inspect both server windows; no stored projects were deleted.'
    }
    Write-Host 'Workspace ready: http://127.0.0.1:5173' -ForegroundColor Green
    Write-Host 'Close the API and Web console windows to stop GeoFathom.'
    Start-Process 'http://127.0.0.1:5173'
    exit 0
}

# Playwright owns its API, frontend, SQLite and imagery directories.
Require-FreePorts
$logDir=Join-Path $root 'data\local-acceptance'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile=Join-Path $logDir ('acceptance-'+$Mode.ToLowerInvariant()+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.txt')
Start-Transcript -Path $logFile -Force | Out-Null
$previousPath=$env:Path
try{
    # Playwright launches its backend with bare python; inherit the same
    # virtual environment used by the numerical acceptance checks above.
    $env:Path=(Split-Path -Parent $venv)+[IO.Path]::PathSeparator+$previousPath
    if($Mode -eq 'Full'){
        $cmake=CommandPath 'cmake.exe'
        Checked $cmake @('-S','.','-B','build/native-local-msvc','-A','x64') 'Configure MSVC C++ native kernels'
        Checked $cmake @('--build','build/native-local-msvc','--config','Release','--parallel') 'Compile C++ native kernels'
        Checked (CommandPath 'ctest.exe') @('--test-dir','build/native-local-msvc','--build-config','Release','--output-on-failure') 'Native CTest acceptance'
        $dll=Join-Path $root 'build\native-local-msvc\Release\geofathom_native.dll'
        if(-not (Test-Path -LiteralPath $dll)){throw "Native DLL missing: $dll"}
        $env:GEOFATHOM_NATIVE_LIBRARY=$dll
        $env:GEOFATHOM_REQUIRE_NATIVE='1'
        Checked $venv @('scripts/run_acceptance.py','-q') 'Complete Python GIS/Terrain tests with C++ native'
    }else{
        Checked $venv @('scripts/run_acceptance.py','-q',
            'tests/test_terrain.py','tests/test_terrain_professional.py',
            'tests/test_terrain_advanced.py') 'Focused numerical GIS/Terrain acceptance'
    }
    Push-Location -LiteralPath $web
    try{
        Checked $npm @('run','build') 'Web typecheck and production build'
        Checked $npm @('test') 'All frontend unit regressions'
        Checked (CommandPath 'npx.cmd') @('playwright','install','chromium') 'Install/verify Chromium'
        $env:GEOFATHOM_E2E_REUSE_EXISTING='0'
        $env:GEOFATHOM_E2E_WORKERS='1'
        $env:GEOFATHOM_E2E_DATABASE_PATH='data/e2e-geofathom-local-serial.sqlite'
        if($Mode -eq 'Quick'){
            Checked $npm @('run','test:e2e','--',
                'e2e/place-terrain-continuity.spec.ts',
                'e2e/terrain-workbench.spec.ts',
                'e2e/terrain-advanced-modes.spec.ts',
                'e2e/core-project-isolation.spec.ts') 'Real Chromium Terrain and project-isolation workflows'
        }else{
            Checked $npm @('run','test:e2e') 'All real Chromium workflows, serial and no retries'
            $env:GEOFATHOM_E2E_WORKERS='4'
            $env:GEOFATHOM_E2E_DATABASE_PATH='data/e2e-geofathom-local-parallel.sqlite'
            Checked $npm @('run','test:e2e') 'All real Chromium workflows with four workers'
        }
    }finally{Pop-Location}
    Write-Host ''
    Write-Host "PASS: $Mode scientific acceptance completed." -ForegroundColor Green
    Write-Host "Log: $logFile"
}catch{
    Write-Host ''
    Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $logFile"
    throw
}finally{
    $env:Path=$previousPath
    Remove-Item Env:\GEOFATHOM_REQUIRE_NATIVE -ErrorAction SilentlyContinue
    Remove-Item Env:\GEOFATHOM_NATIVE_LIBRARY -ErrorAction SilentlyContinue
    Remove-Item Env:\GEOFATHOM_E2E_DATABASE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\GEOFATHOM_E2E_WORKERS -ErrorAction SilentlyContinue
    Stop-Transcript | Out-Null
}
