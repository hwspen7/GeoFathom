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


## Repeatable Windows acceptance

Run the file-backed entry point instead of piping Python into stdin:
`python scripts/run_acceptance.py -v -rs --tb=short`.
Windows multiprocessing spawn must be able to reload the parent entry file.
The launcher is CPU-only compatible; enable the existing hardware test flags
and configure a disposable PostGIS DSN explicitly for full qualification.

The active CUDA toolkit is discovered through CUDA_PATH (bin/x64 or bin).
An operator may set GEOFATHOM_CUDA_BIN to an existing absolute directory
containing the matching CUDA runtime DLL. The native loader retains the
Windows DLL search handle; ONNX CUDA session initialization preloads CUDA
and cuDNN when the installed ONNX Runtime provides the preload API.
The runtime rejects whole-provider CUDA-to-CPU fallback. Ordinary ONNX
per-node CPU placement is still possible for unsupported operators; strict
hardware qualification requires a profiling-based CUDA operator audit.


### Automated local host workflow

After installing the project test dependencies, ONNX, the matching GPU ORT
package/cuDNN, CUDA Toolkit, CMake/MSVC, Docker and Node.js, run from the root:

```powershell
python scripts/host_acceptance.py --soak-seconds 60
```

Use `--docker ABSOLUTE_DOCKER_EXE` if the CLI is outside PATH.
The script creates a disposable loopback-only PostGIS container with an
ephemeral port and generated password, and stops only that container.
An existing **disposable** test database can be explicitly opted into with
`--reuse-test-postgis` and GEOFATHOM_TEST_POSTGIS_DSN. It does not install
system tools or alter the production .env. Reports, isolated data, native
builds, synthetic ONNX fixture and GPU profiling are under
`build/host-acceptance/<run-id>`. The full Python run rejects skipped tests,
records statement/branch coverage, and the web suite starts fresh test
servers. Keep ports 8000 and 5173 free. `--skip-web` explicitly omits web
qualification. `--soak-seconds 86400` runs separate 24-hour CPU and GPU
soaks; synthetic model qualification still does not measure real
satellite segmentation accuracy or physical multi-host behavior.


### Qualification is distinct from a successful smoke run

The host report records the tested commit, tracked-tree status, runtime versions,
CPU/GPU and per-stage results. A new report always remains isolated in its own
directory. Pass `--baseline <previous-report-directory>` to compare the
same-hardware, same-duration CPU/CUDA throughput and ONNX p95 inference latency.
The default regression allowance is 15 percent. Use
`--max-regression-percent` to explicitly select another bound.

The CUDA soak records sampled total device memory **and** runtime-owned device
allocation; the latter is not total process VRAM. Use an otherwise idle,
non-remapped GPU when collecting comparable acceptance measurements.
The device-wide measurement can include other applications. A long soak still
does not exercise every real-world model or GIS pipeline.

Coverage collection now includes Python threads and subprocesses, subject to
coverage data being flushed at child shutdown. An intentionally killed child
may not produce a coverage file. The separate GCC CPU instrumented CTest build
uses atomic gcov counters; it measures host C++ code, not CUDA device branches.
The strict quality-report utility rejects insufficient coverage rather than
declaring a general release qualified after a successful smoke run.

```bash
python scripts/quality_report.py --python coverage.json --native native-coverage.xml --web web/coverage/coverage-summary.json --output quality.json
```

Release coverage targets are 95% Python statements, 90% Python branches,
90% native CPU lines, 90% frontend statements and 85% frontend branches.
These are gates to satisfy using measured reports, not asserted achievements.


Frontend coverage uses the same locked Vitest version and coverage provider:
`cd web; npm ci; npm run test:coverage`. The resulting summary includes all
uncovered application files, so high coverage of three geometry helper suites
must not be mistaken for high coverage of the whole UI. Browser E2E reports
are separate from unit coverage.


### Independent model and multi-host gates

For a real operator-provisioned model, set GEOFATHOM_VISION_MODELS_DIR and
provide a JSON dataset manifest with a dataset_id, model_id and scenes:
each scene has image, labels, and optional scl paths relative to the manifest.
Run `python scripts/model_qualification.py --dataset labels.json --min-iou 0.8 --min-coverage 0.95 --output model-quality.json`.
Choose thresholds for the intended application before evaluating. Synthetic
acceptance weights are rejected. This reports unfiltered aggregate accuracy,
confidence retention, per-class support, hashes and scene-level metrics.

For distributed qualification, provision a disposable PostgreSQL database
and a shared archive on both nodes. Set GEOFATHOM_DISTRIBUTED_DSN privately
on both. Choose a new acceptance-* queue and distinct compute node name.
On the compute host run:

```text
python scripts/distributed_acceptance.py worker --queue acceptance-example --archive <shared-directory> --node compute-b
```

On the coordinator host run:

```text
python scripts/distributed_acceptance.py coordinator --queue acceptance-example --archive <shared-directory> --expected-node compute-b --output broker-quality.json
```

The probe verifies the actual broker-assigned node and real raster counts
from the shared content-addressed archive. Physical separation is an
operator-established fact, not something a hostname string proves.
The test suite also runs a separate worker interpreter on one host.


### Resuming long native acceptance safely

Every completed native CPU/CUDA stage records hashes of the exact Release DLL,
CTest logs and passed soak result. To reuse those stages after an unrelated
later failure, pass `--resume <previous-run-directory>` with the same
`--soak-seconds`. Source commit, clean tree, hardware, toolchain, dependency
versions and artifact hashes must match. A fresh report directory is always
created; database, synthetic GPU inference and web checks are rerun, and a
missing native stage is executed from scratch. Do not resume after source or
driver changes.

The CI quality-measurement job merges the raw Linux, Windows and live PostGIS
Python coverage data, not percentages. It publishes the combined XML/JSON and
the measured target verdicts. The report-only flag does not qualify a release;
the standalone strict quality gate (without that flag) exits nonzero if any
target is unmet.


### Current quality policy

Normal development host acceptance retains a 60-second CPU/CUDA soak;
the final extended local qualification uses `--soak-seconds 600` for each
device. A 24-hour run is optional, not a required gate. Combined frontend
coverage uses identical Istanbul instrumentation of original application
source in Vitest and real Chromium. All production TS/TSX files remain in
the denominator, including those never loaded. Unit and browser summaries
are emitted separately and the combined report is calculated from counters,
not from adding percentages. Native CPU line and branch goals are 95% and
85%; Python targets remain 95% statements and 90% branches, frontend targets
90% statements and 85% branches.


CI has two distinct jobs: quality-measurement publishes the actual combined
measurements even if targets are unmet; quality-targets fails on each unmet
threshold or comparable metric regression floor. The earlier unit-only
frontend metric is deliberately not used as a baseline for the new
instrumentation. A successful Windows short run is functional/hardware
evidence; `--require-coverage-targets` additionally enforces its local
Python and combined web coverage. The independent GCC CI job provides native
line/branch evidence.


### Core capability acceptance (research and personal GIS scope)

The project prioritizes correctness of these six capabilities over pursuing
coverage percentages in unrelated enterprise integrations. The complete
host acceptance remains required, including zero failed or skipped Python
tests, actual native CPU/CUDA tests, strict synthetic ONNX GPU inference,
real isolated PostGIS, and browser E2E. Global coverage is still reported
and the separate strict coverage check is retained; it is not proof of
algorithmic precision. Final project-level resource soak is 600 seconds per
device, not 24 hours.

- Geodesy: WGS84 area, complete exterior/hole boundary perimeter, ring
  winding independence, multipart sums, numeric control points and finite
  structurally valid coordinates. Horizontally measured, not legal survey
  accuracy or 3D terrain surface area.
- CRS: explicit horizontal 2D EPSG contracts, longitude/latitude order,
  independent Web Mercator equations, UTM control points and round trips.
  Reject unsupported vertical/3D systems and unavailable non-ballpark
  transforms; geodetic datum/epoch accuracy still depends on installed PROJ
  operations and source metadata.
- CPU/CUDA: seeded adverse inputs, odd tile sizes, exact masks and class
  IDs, normalized index absolute tolerance of 1e-6, fused pipeline and
  allocation trim checks on real hardware.
- Memory: variable-size continuous native computation, sampled host/device
  growth, allocator limits and cleanup, with existing sanitizer and fuzzer
  jobs. Bounded tests cannot prove absence of all leaks.
- Storage: atomic optimistic writes, coherent workspace snapshots, complete
  revision history, locked layers and cross-project identity checks.
- Map editing: real Chromium and MapLibre interactions, revision history
  isolation, stale response fencing, undo/redo and saved-feature identity.
