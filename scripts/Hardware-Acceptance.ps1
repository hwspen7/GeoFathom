# Run on the operator's actual RTX 4070 Ti SUPER machine, not a hosted CPU runner.
param(
    [ValidateRange(5,86400)][int]$SoakSeconds = 60,
    [string]$Model = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Hardware acceptance command failed ($LASTEXITCODE)." }
}
Invoke-Checked { nvidia-smi }
$gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader | Out-String)
if ($gpu -notmatch "4070 Ti SUPER") { throw "Expected RTX 4070 Ti SUPER was not detected." }
Invoke-Checked { cmake -S . -B build/native-cuda -DGEOFATHOM_NATIVE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 }
Invoke-Checked { cmake --build build/native-cuda --config Release --parallel }
Invoke-Checked { ctest --test-dir build/native-cuda --build-config Release --output-on-failure }
$dll = Get-Item build/native-cuda/Release/geofathom_native.dll -ErrorAction SilentlyContinue
if (-not $dll) { throw "CUDA Release native DLL missing." }
$env:GEOFATHOM_NATIVE_LIBRARY = $dll.FullName
$env:GEOFATHOM_REQUIRE_NATIVE = "1"
$env:GEOFATHOM_SPECTRAL_DEVICE = "cuda"
Invoke-Checked { python benchmarks/soak.py --seconds $SoakSeconds --device cuda --output hardware-soak.json }
if ($Model) {
    $env:GEOFATHOM_VISION_DEVICE = "cuda"
    $env:GEOFATHOM_VISION_DEVICE_POSTPROCESS = "1"
    Invoke-Checked { python benchmarks/gpu_acceptance.py --model $Model --runs 100 }
} else {
    Write-Warning "No installed ONNX model specified; real CUDA model inference is not qualified."
}
