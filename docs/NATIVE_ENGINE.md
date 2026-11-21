# Native computation engine

The local-first GIS engine uses C++17 for bounded, performance-sensitive
primitives. Python owns API orchestration and data-model validation.
GDAL/Rasterio (C/C++) handles raster I/O and coordinate transforms;
GEOS/Shapely handles authoritative geometry validity/polygonization;
PROJ/PyProj handles geodesic measurements. Rewriting their established
algorithms in custom C++ would add numerical risk without justified speed.

## Implemented kernels

| Capability | Native ABI | Python call site |
| --- | --- | --- |
| Ring containment and bbox intersection | `gf_contains_ring`, `gf_bbox_overlaps` | `geometry.topology` |
| Region growing over RGB | `gf_seeded_rgb_region` | `geometry.mask` |
| Metric vertex/edge snapping | `gf_snap_point` | `geometry.editing` |
| Simple-ring crossing validation | `gf_ring_self_intersects` | `geometry.editing` |
| Line simplification | `gf_simplify_line` | `geometry.editing` |
| Immutable metric-segment BVH | `gf_spatial_index_build/query/destroy` | `geometry.spatial.SegmentIndex` |
| Batched nearest-segment lookups | `gf_spatial_index_query_batch` | `SegmentIndex.query_many` |
| Horn terrain mean/max gradient | `gf_dem_gradient` | `terrain.engine` |
| Normalized spectral difference | `gf_spectral_normalized_difference` | `geometry.spectral.normalized_difference` |
| Spectral gain/loss classification | `gf_spectral_change` | `geometry.spectral.classify_change` |

The spectral kernels receive contiguous two-dimensional float32 arrays and
uint8 validity masks, process at most 16 million pixels per call and return
integer accepted/changed counts or a negative error code. Zero denominators,
NaN/Infinity and invalid masks are explicitly excluded; returned scores are
clipped to [-1, 1]. Change labels are 0=unchanged/invalid, 1=gain, 2=loss.
Neither kernel interprets spectral band identities, date metadata or image
georeferencing.

The BVH is allocated with RAII during construction to avoid leaking a
partially built tree on exceptions. The returned handle owns immutable
native memory; Python's `SegmentIndex` closes it through a context manager
or explicit `close()`. Queries after closing are rejected, and repeated
close operations are harmless. The batch interface accepts 1 to 1,000,000
finite projected XY positions, returns hit flags and four values per hit
(x, y, distance in meters, source-segment index), and amortizes the Python
FFI boundary. The current Python front end further caps batches at 100,000
queries per request.

## Build and verify

```bash
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release --parallel
ctest --test-dir build/native --build-config Release --output-on-failure
python -m pytest -q tests/test_spectral_native.py tests/test_geoai.py tests/test_spatial.py
```

Run native sanitizers on GCC/Clang:

```bash
cmake -S . -B build/native-sanitized -DCMAKE_BUILD_TYPE=Debug -DGEOFATHOM_NATIVE_SANITIZERS=ON
cmake --build build/native-sanitized --config Debug --parallel
ctest --test-dir build/native-sanitized --build-config Debug --output-on-failure
```

The GitHub workflow also runs Release and Debug native tests, Windows MSVC
DLL tests, and the Python suite with `GEOFATHOM_REQUIRE_NATIVE=1`.
Cross-language parity compares randomized raster data, noncontiguous
NumPy views, invalid pixels, extreme values and threshold behavior with
the fallback implementation. Stress cases exercise hundreds of thousands
of raster pixels and 100,000-indexed metric segments. Runners are shared
and variable, so the smoke tests intentionally do not assert a particular
relative speedup.

## Remaining engineering work

The kernels are an important foundation, not a completed high-performance
GIS runtime. The next implementation targets are:

1. Memory-budgeted, incremental out-of-core raster tile processing and
   distributed/parallel task scheduling for multi-gigapixel scenes.
2. No-copy GPU tensor handoff with an explicit CUDA/ONNX execution and
   synchronization contract, keeping CPU fallback.
3. Persistent, reusable spatial indexes and independent, concurrent edit
   snapshots for projects with millions of features.
4. Chunked connected-component stitching across tile boundaries, with
   polygon provenance and topology quality checks.
5. Hardware-measured latency/throughput profiles and stress/soak runs on
   real imagery including nodata, multispectral sensors and CRS changes.
6. Architecture-level fuzzing for C ABI input contracts and sanitizer
   validation on additional operating systems and compiler versions.

These are deliberately marked outstanding until implemented and tested.
