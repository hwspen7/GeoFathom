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

## Recent native and job-data improvements

- BVH point queries use bounded stack storage, removing a heap allocation
  per query, with finite projected-coordinate and tolerance validation.
- NumPy float64 segment input is passed directly to native BVH construction
  via a contiguous pointer, instead of creating a second Python list and
  ctypes array for every endpoint.
- Native reader leases permit concurrent lookups. Closing the index marks
  it unavailable to new readers and waits for all in-flight queries before
  freeing its native memory.
- Corner-adjacent pixels use 4-connected raster polygonization to avoid
  self-touching invalid rings; unexpected invalid polygon repair requires
  conservation of polygonal area.
- Streaming jobs preflight local disk scratch and cap fragmented masks before
  GDAL polygonization; these checks do not constitute a hard process RSS limit.
- SQLite worker progress uses a lightweight connection and checks cancellation
  periodically rather than running schema initialization and a write on every
  tile. Full-resolution operations share one process-local raster execution
  gate. Large task results are stored separately and downloaded on demand.
- Local imaging assets are hashed with SHA-256; reproducibility metadata
  preserves the active analysis engine, model identifier and model hash.
- The default Linux Python CI suite runs both synthetic 4K and 8K image
  processing, but real-world image complexity, GPU memory pressure and
  calibrated AI accuracy require additional acceptance runs.

Performance measurements are available through
`python benchmarks/native_pipeline.py --size 4096 --segments 100000`.
The measurements are environment-specific and exclude GDAL I/O and GPU
transfer; do not treat synthetic microbenchmark speedup as proof of whole
pipeline performance.

## SQLite connection initialization

The local SQLite base schema and R-tree backfill now run only when
`PRAGMA user_version` indicates an uninitialized or legacy database.
Each new connection still registers the geometry UDFs needed by SQLite
spatial triggers, but repeated API reads no longer execute schema DDL
and full-table index-count comparisons. Explicit index rebuild still uses
`prepare_rtree`. External direct writes that bypass/destroy the triggers
need an explicit rebuild; multiple processes still require a shared
job lease coordinator before production multi-worker deployment.

### Spatial-index recovery rule

The fast viewport query performs an inexpensive index-existence probe.
If source features exist but `feature_bounds` has been entirely cleared,
the index is backfilled before returning a page. This preserves recovery
after an interrupted or externally deleted index without running full
feature-count scans on every API call. Partial out-of-band corruption still
requires the explicit spatial-index rebuild operation.

CI now also sets `GEOFATHOM_STRESS_MILLION_SEGMENTS=1` in the
Linux native/Python acceptance run, so the 1,000,000-segment BVH build
and 10,000 batched nearest-neighbor queries are exercised on a real
GitHub runner, with no fixed speedup threshold.
