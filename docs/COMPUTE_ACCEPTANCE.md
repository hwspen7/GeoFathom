# Compute runtime and acceptance

## Native execution

The C++ worker pool executes independent pixel spans; aligned scratch-buffer
leases are used for streamed inference (64-byte alignment, bounded allocator,
zeroed reuse). SSE2 mask counting has a scalar fallback. The optional CUDA
library provides spectral kernels and a fused two-date index pipeline. Two
normalized indices stay on the GPU during fused change computation; raw
GeoTIFF bands and the final classification still cross the bus. This is not
a fully GPU-resident end-to-end GIS pipeline.

`GEOFATHOM_SPECTRAL_DEVICE=auto` selects a CUDA-capable native library for a
configured minimum tile size and falls back to CPU after a CUDA error.
Explicit `cuda` is strict. CUDA buffers have a configured fixed capacity;
they are reused but do not guarantee driver-wide VRAM limits. ONNX batches
are opt-in via model manifest `max_batch` (1–16); the actual batch is bounded
by the tensor and task budgets. Model must support dynamic batch dimension
if max_batch exceeds one. Halo overlap retains disjoint tile cores.

Optional `GEOFATHOM_CPU_CORES_PER_WORKER` applies disjoint local affinity
groups for isolated worker slots on Linux/Windows. `GEOFATHOM_RASTER_AS_MB`
is a CPU-only Linux virtual-address limit; the RSS monitor remains sampled.
Process limits are not a global hard resident-memory quota for GDAL, CUDA
and the entire operating system.

## Raster and remote inputs

Get `/imagery/{id}/pyramid` and `/imagery/{id}/tiles/{level}/{x}/{y}.png`.
Levels are source-pixel-grid levels, not Web Mercator XYZ. The persistent
SQLite cache bounds PNG payload bytes, not the database's physical size.
Tile rendering uses a single sampled stretch per source identity.
Default streaming cap remains 67,108,864 pixels. An operator may opt in
to a larger cap up to 400,000,000 pixels, subject to source dimensions,
scratch capacity and complexity constraints.

Default remote processing uses Earth Search via GDAL range requests.
Additional trusted providers are configured by JSON with URL, allowed
collections/hosts and NIR/red/SCL asset names. A configured resumable
asset cache uses strong ETag, byte ranges, advertised content length and
SHA-256. Cached asset directory and archival versions need filesystem quotas
and retention managed by the operator; cache locks left by abnormal process
exit require operator cleanup after confirming no owner is alive. No
untrusted arbitrary URL inputs or automatic redirect follow are allowed in
the HTTP cache. All providers still require meaningful Sentinel-2-like
quality codes compatible with the processing contract.

## Distributed compute

Install `.[postgis]`, then configure `GEOFATHOM_DISTRIBUTED_DSN` and a
shared content-addressed `GEOFATHOM_VERSION_DIR` on the API and worker.
The optional `GEOFATHOM_DISTRIBUTED_QUEUE` isolates pools. Run each worker:

```bash
python -m jobs.distributed --node distinct-machine-name
```

PostgreSQL owns queue claims and leases; one slot per named node. Only pure
local spectral and semantic tasks are dispatched remotely. Assets are
verified private copies of immutable archive objects, and project writes
remain local. Do not mount SQLite across hosts. Real PostgreSQL plus
spawned isolated processing is covered by CI; separate physical hosts,
network partition and high-volume distributed acceptance are operator-run.

## Maintenance and security

The version-2 SQLite migration installs project RBAC tables transactionally.
Newer unknown schema versions fail closed. Legacy base bootstrap remains
compatible. Back up consistently with the SQLite backup API:
`python -m storage.maintenance --backup-dir backups --retain 7 --interval 3600`.
Restore only to a new path:
`python -m storage.maintenance --restore-from backups/file.sqlite --restore-to restored.sqlite`.
The operator must review the recovered DB before switching the API path.
Only the operator can create project users and assign viewer/editor roles:

```bash
python -m core.access create "Analyst"
python -m core.access grant USER_ID PROJECT_ID viewer
python -m core.access revoke USER_ID --project PROJECT_ID
```

Project members can read assigned projects and editors can perform supported
project writes; administrative and global imagery endpoints are denied.
OIDC/password login is not included. `/health/metrics` reports bounded
request/job/RSS/cache/disk counters and alerts for operator collection.
Linux/PostGIS/Windows Python 3.11 constraint locks are generated from
successful CI environments; npm uses its committed package lock.
A version tag triggers a release bundle build/test/checksum/publish workflow.

## Test policy

Hosted CI: Release and Debug CTest, ASan/UBSan, TSan, 20,000 libFuzzer
mutations, randomized differential/parity tests, spawned concurrency,
native 4K/8K/16K stress, model/label batch contracts and actual tiny ONNX
CPU inference, failed-process cleanup, SQLite restore and real PostgreSQL
ownership/worker tests, API authorization, TypeScript and Chromium.
The native soak gate measures continuous CPU correctness, throughput and
RSS growth for 10 seconds. Run hardware qualification independently:

```powershell
.\scripts\Hardware-Acceptance.ps1 -SoakSeconds 86400 -Model installed_model
```

RTX 4070 Ti SUPER CUDA build, GPU parity, 24-hour actual resource soak,
actual satellite model accuracy and multi-host physical acceptance require
hardware, models, annotation and nodes. Short hosted smoke tests are not
a substitute for those results.
