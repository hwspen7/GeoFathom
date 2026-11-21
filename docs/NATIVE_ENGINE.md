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

## Streamed raster engine and model sessions

The full-resolution analysis mode now uses rasterio Window reads with a
configurable tile size (64, 128, 256 or 512 pixels for spectral operations;
the ONNX manifest's native tile size for semantic inference). It enforces
a per-tile working-set allowance and a maximum of 64 million source pixels
per task. Class masks are written to a temporary GeoTIFF instead of being
assembled in an unbounded array. The final GDAL polygonization reads the
whole disk-backed mask with 8-neighbor connectivity, so adjacent classified
pixels on opposite sides of a tile boundary become one polygon.

Jobs publish monotone progress into the SQLite queue. Cancellation is
checked before every tile and periodically during connected-component
extraction. Processing has bounded candidate count, caps returned polygons
at 100 and deletes its temporary files after completion, failure or
cancellation. These limits do not bound every internal GDAL allocation, and
large pathological shapes may still exceed process RAM.

Local ONNX sessions now use a synchronized model-session pool with explicit
leases, an LRU cache of idle models and a limit on concurrent inference
requests. Session keys include model path, modification time, size and
provider. A session cannot be evicted while another thread uses it.
CPU thread count, tensor working-set budget and CUDA arena advisory limits
are configurable. The CUDA arena option cannot guarantee a process-wide
VRAM limit because model weights, drivers and operators may allocate memory
outside it. No GPU weights are bundled; CUDA execution still requires
actual hardware validation.

Python's metric BVH owner now uses a reentrant lock around query, batched
query and destruction. This trades some parallel query throughput for a
clear use-after-close safety guarantee; native C++ query data itself
remains immutable.

## Remaining engineering work

The kernels are an important foundation, not a completed high-performance
GIS runtime. The next implementation targets are:

1. Distributed raster scheduling and streaming datasets beyond the current
   64-million-pixel task limit.
2. True zero-copy GPU tensor handoff and experimentally validated CUDA
   memory use, throughput and failure recovery.
3. Persistent mmap/disk spatial indexes, concurrently versioned edit
   snapshots and million-feature read/write acceptance benchmarks.
4. Model-context overlap or halo blending to reduce prediction seams in
   tiled semantic inference. Pixel-mask polygon boundaries already join.
5. Hardware-measured sustained throughput, confidence calibration and
   full accuracy validation on real annotated multispectral scenes.
6. Expanded C ABI fuzzing and sanitizer checks across compilers and OSes.

These are deliberately marked outstanding until implemented and tested.
