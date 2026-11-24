# Exercise actual cmd.exe wrappers without running expensive GIS acceptance twice.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('GeoFathom launcher ' + [guid]::NewGuid().ToString('N'))
$checkout = Join-Path $fixture 'checkout with spaces'
$other = Join-Path $fixture 'unrelated directory'
$receipt = Join-Path $fixture 'receipt.txt'
$cases = [ordered]@{
    'Start-GeoFathom.bat' = 'Start'
    'Test-Terrain-Quick.bat' = 'Quick'
    'Test-GeoFathom-Full.bat' = 'Full'
}
try {
    New-Item -ItemType Directory -Path (Join-Path $checkout 'scripts'), $other -Force | Out-Null
    foreach ($launcher in $cases.Keys) {
        Copy-Item -LiteralPath (Join-Path $root $launcher) -Destination $checkout
    }
    @'
param([string]$Mode)
Set-Content -LiteralPath $env:GEOFATHOM_LAUNCHER_TEST_RECEIPT -Value @($Mode, (Get-Location).Path)
exit ([int]$env:GEOFATHOM_LAUNCHER_TEST_EXIT)
'@ | Set-Content -LiteralPath (Join-Path $checkout 'scripts\Local-Research.ps1') -Encoding ASCII
    $env:GEOFATHOM_LAUNCHER_TEST_RECEIPT = $receipt
    Push-Location -LiteralPath $other
    try {
        foreach ($launcher in $cases.Keys) {
            foreach ($expected in @(0, 7)) {
                $env:GEOFATHOM_LAUNCHER_TEST_EXIT = [string]$expected
                Remove-Item -LiteralPath $receipt -ErrorAction SilentlyContinue
                $path = Join-Path $checkout $launcher
                & $env:ComSpec /d /c ('call "' + $path + '" --no-pause')
                $actual = $LASTEXITCODE
                if ($actual -ne $expected) { throw "$launcher exit $actual, expected $expected" }
                $values = @(Get-Content -LiteralPath $receipt)
                if ($values.Count -ne 2 -or $values[0] -ne $cases[$launcher] -or $values[1] -ne $checkout) {
                    throw "$launcher did not preserve mode or checkout directory"
                }
                Write-Host "PASS: $launcher mode=$($cases[$launcher]) exit=$actual"
            }
        }
    } finally { Pop-Location }
} finally {
    Remove-Item Env:\GEOFATHOM_LAUNCHER_TEST_RECEIPT, Env:\GEOFATHOM_LAUNCHER_TEST_EXIT -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}

# All six assertions succeeded. Do not propagate the last intentionally failing child process.
# Any unexpected exit code or receipt mismatch above still throws before this point.
exit 0
