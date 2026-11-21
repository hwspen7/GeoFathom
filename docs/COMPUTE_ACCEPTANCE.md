# Compute runtime and acceptance

## Native execution

The C++ worker pool executes independent pixel spans; aligned scratch-buffer
leases are used for streamed inference (64-byte alignment, bounded allocator,
zeroed reuse). Mask counting dispatches AVX2, SSE2, ARM64 NEON or scalar at runtime; each available implementation is tested against an independent scalar reference. The optional CUDA
library provides spectral kernels and a fused two-date index pipeline. Two
normalized indices stay on the GPU during fused change computation; raw
GeoTIFF bands and the final classification still cross the bus. This is not
a fully GPU-resident end-to-end GIS pipeline.

`GEOFATHOM_SPECTRAL_DEVICE=auto` selects a CUDA-capable native library for a
configured minimum tile size and falls back to CPU after a CUDA error.
Explicit `cuda` is strict. CUDA buffers grow on demand within the configured spectral byte budget, support explicit trimming, and are reused. Driver-wide VRAM is not guaranteed by the allocator. ONNX batches
are opt-in via model manifest `max_batch` (1–16); the actual batch is bounded
by the tensor and task budgets. Model must support dynamic batch dimension
if max_batch exceeds one. Halo overlap retains disjoint tile cores.

Optional `GEOFATHOM_CPU_CORES_PER_WORKER` applies disjoint local affinity
groups for isolated worker slots on Linux/Windows. `GEOFATHOM_RASTER_AS_MB`
is a CPU-only Linux virtual-address limit; the RSS monitor remains sampled.
For aggregate isolated worker memory, configure GEOFATHOM_WORKER_MEMORY_MB. Linux requires a delegated cgroup v2 with memory.max at or below that limit; Windows uses a shared named Job Object committed-memory limit. Both fail closed if the boundary cannot be applied. This is not a limit on unrelated OS processes or CUDA VRAM.

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

## Production recovery and resident GPU processing

`python -m storage.incremental backups/archive.sqlite capture --retain 7 --interval 3600`
stores only new 64 KiB chunks from a consistent online backup snapshot.
Restore any retained generation using
`python -m storage.incremental backups/archive.sqlite restore GENERATION restored.sqlite`.
Capture reads a full consistent snapshot before deduplication; the archive
stores incremental data, not incremental capture I/O. SQLite can reuse freed
pages; the archive file need not shrink immediately after retention pruning.

Configure an HTTPS receiver via `GEOFATHOM_ALERT_WEBHOOK` and run
`python -m core.alerts --state data/alert-state.sqlite` as a separate process.
Alert transitions are persisted and retried, with stable event IDs and
recovery messages. Delivery is at least once; receivers should deduplicate.

CUDA spectral memory uses a demand-grown pool capped by
`GEOFATHOM_CUDA_SPECTRAL_BUDGET_MB`. Trusted CuPy callers may chain
`geometry.device_arrays` functions directly on resident buffers.
For ONNX Runtime float32 logits and supported integer labels, enable
`GEOFATHOM_VISION_DEVICE_POSTPROCESS=1`. Native CUDA borrows the output
OrtValue, computes final class IDs and confidence on device, and returns
only those compact arrays to CPU GIS. GDAL source input and GIS outputs
still cross device boundaries. Model admission uses weighted per-device
session and active tensor reservations, not actual global driver VRAM usage.

The release workflow also builds and verifies the full Linux/Windows
archive on pull requests without publishing a tag. CUDA compilation, ARM64
parity and real Linux cgroup enforcement have separate CI jobs. Actual
CUDA, 24-hour soak and multi-host hardware acceptance remain mandatory
for production hardware qualification.
