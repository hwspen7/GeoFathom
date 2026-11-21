# Multi-dimensional validation matrix

The tests below are automated against the real code in the repository.
They do not by themselves certify cadastral accuracy, GPU performance or
a production multi-user deployment.

| Area | What is checked | Test location |
| --- | --- | --- |
| Basic spatial geometry | Polygons, holes, line lengths, geodesic WGS84, malformed coordinates | \`tests/test_geo.py\`, \`tests/test_robustness.py\` |
| Seeded numeric fuzz | 240 varied geodesic rectangles, containment, area/perimeter comparisons | \`tests/test_robustness.py\` |
| C++ native kernels | Point/snap, ring intersections, segmentation, 100K BVH edges, Horn DEM known slope | \`geometry/native/test_geometry.cpp\` |
| Spatial indexing | Native nearest edge, path segments, native fallback policy, large index | \`tests/test_spatial.py\`, \`web/src/spatialIndex.test.ts\` |
| Polygon editor | Move, add/remove corners, rings, live estimates, undo/redo, geodesic moves | \`web/src/editing.test.ts\` |
| Topology/trace | Adjacent shared node, locked rollback, disconnected network | \`tests/test_topology_shared.py\`, \`tests/test_tracing.py\` |
| Projects/history | Atomic splits, undo by revision, locked/delete isolation, default layer | \`tests/test_workspace.py\` |
| Attributes | Queries, filters, type handling, versioned bulk updates, lock rollback | \`tests/test_attributes.py\` |
| Cartographic API | Default/persisted style, bad colors/zoom, collision flags, conflict, project isolation | \`tests/test_cartography.py\` |
| Categorized styling | Unique category palettes, unknown fallback, class legend | \`tests/test_cartography.py\`, \`web/src/labels.test.ts\` |
| Labels | Name, source, area, length, custom attributes, zoom, Unicode, control text, note overrides | \`web/src/labels.test.ts\` |
| Notes & security | WGS84 validation, Unicode text, locks, cross-project access, XSS-like input | \`tests/test_cartography.py\`, \`web/e2e/labels.spec.ts\` |
| Vector interchange | GeoJSON, GeoPackage CRS, KML, GPX, Shapefile ZIP, ZIP traversal defense | \`tests/test_vectorio.py\` |
| Raster terrain | Synthetic known-incline DEM, height statistics, profile | \`tests/test_terrain.py\` |
| Vision prompt correction | Georeferenced SAM inputs, bounds, mocked masks, unavailable model handling | \`tests/test_refine.py\` |
| Project scaling | 200 saved features, batched writes, map style and class persistence | \`tests/test_robustness.py\` |
| Concurrency | Simultaneous stale-revision attempts accept one writer | \`tests/test_robustness.py\` |
| Browser E2E | Actual drawing, vertices/undo, project save, import and attribute table | \`web/e2e/survey.spec.ts\` |
| Browser labeling | Configure labels, reload, place/edit/delete note, classified legend, identify | \`web/e2e/labels.spec.ts\` |
| Cross-platform CI | Linux Python and C++ Release/Debug, Windows MSVC, Web production build | \`.github/workflows/checks.yml\` |
| Coverage | Python statement coverage report for geometry, storage, terrain and vision | CI artifact \`geofathom-python-coverage\` |

## Run locally

\`\`\`powershell
python -m pip install -e ".[dev]"
cmake -S . -B build/native
cmake --build build/native --config Release
ctest --test-dir build/native --build-config Release --output-on-failure
python -m pytest -q --cov=geometry --cov=storage --cov=terrain --cov=vision --cov-report=term-missing

cd web
npm install
npm run build
npm test
npx playwright install chromium
npm run test:e2e
\`\`\`

The Playwright suite starts FastAPI and Vite automatically. Run it from the
\`web\` directory with ports 8000 and 5173 available.

## Interpreting results

- Browser unit tests verify data-level label generation and style
  preparation; only Chromium E2E exercises real UI controls.
- A scale or density test demonstrates a sampled workload, not a hard
  performance service-level objective. Record CPU, GPU, p95 latency,
  memory and project sizes before setting a production limit.
- The C++ million-segment cap is a guardrail, not a guaranteed real-time
  throughput claim.
- The optional SAM 2 CUDA path requires a locally installed model and an
  actual GPU for performance acceptance.
- Linux and Windows CI each need a fresh successful run **on the latest
  commit**, not an older green check.

## Remaining professional GIS capabilities

The implemented workflow includes rectangle/polygon spatial selection,
topology inspection, regional vector PDF export, graduated colors,
conditional/dragged labels, project EPSG conversions and projected grids,
OGC service connectors, indexed SQLite/PostGIS pages, and persistent jobs.

Still outside the current scope:

1. Full alternative-projection basemap rendering, including antimeridian and
   polar map editing.
2. Multi-user authoritative PostGIS editing with identity, row permissions,
   audit trails, concurrent conflict handling, and live replication.
3. Distributed processing, durable multi-process scheduling, and GPU worker
   orchestration instead of the local two-thread worker pool.
4. Streaming vector tiles, out-of-core editing and validated million-feature
   end-to-end rendering benchmarks.
5. Automated topology repair with review/preview and transactionally audited
   topology changes.
6. Fully offline map tiles/fonts and broad real-world WMS/WMTS/WFS provider
   interoperability tests. External service success is configuration-dependent.

Existing automated tests establish correctness for synthetic workloads and
configured CI services, not legally accurate surveying or production
scale/performance guarantees.

## Professional GIS integration coverage

- \`tests/test_pro_spatial.py\`: R-tree maintenance, viewport pagination,
  exact predicates, overlap/duplicate/gap/dangle detection.
- \`tests/test_printing.py\`: vector PDF paper sizes, text extraction,
  scale/legend and project scope.
- \`tests/test_professional_p1.py\`: equal/quantile/Fisher–Jenks, EPSG
  transformations, graticules, style validation.
- \`tests/test_ogc_services.py\`: WMS GetMap, WMTS GetTile, WFS and OGC API
  Features providers, HTTPS allowlist security and permission boundaries.
- \`tests/test_background_jobs.py\`: persistent job execution, cancellation,
  progress, error, JSON export and administrator-only operations.
- \`tests/test_postgis.py\`: optional real PostGIS query and geometry sync,
  with a dedicated \`postgis\` GitHub Actions service job.
- \`web/e2e/professional.spec.ts\`: actual Chromium map selection, PDF download,
  topology QA, graduated colors, project CRS and queued export.

- \`tests/test_professional_p1.py\` and \`web/src/labels.test.ts\`:
  safe conditional label filters and advanced typography.
- \`web/e2e/professional.spec.ts\`: drag-to-position map label
  stores per-feature offsets with revision history.

## GeoAI raster acceptance coverage

- `tests/test_geoai.py`: known synthetic NDVI mask, WGS84 area/provenance,
  reprojected two-date gain/loss, invalid bands, nonoverlap, admin-only
  persistent analysis jobs, project isolation, local vision model manifest,
  simulated ONNX segmentation output and malformed-output rejection.
- `web/e2e/geoai.spec.ts`: real Chromium checks for switching among
  spectral, temporal and semantic workflows without requiring a language prompt.
- True ONNX model inference accuracy, out-of-domain generalization, CUDA GPU
  performance and large-scene scene-by-scene validation require operator-
  provided weights, independently labeled images and physical test hardware.

## Native C++ correctness and lifecycle coverage

- \`geometry/native/test_geometry.cpp\`: direct C ABI tests for polygon,
  color mask, snap, simplification, 100,000-segment BVH, batched indexed
  queries, DEM and nodata-safe spectral kernels.
- \`tests/test_spectral_native.py\`: native/NumPy parity with randomized
  rasters, NaN/Inf, zero denominators, noncontiguous views, threshold edges,
  validation errors and a 768-by-768-pixel stress case.
- \`tests/test_spatial.py\`: index batch/scalar parity, distant misses,
  explicit close and use-after-close checks.
- CI uses Linux Release/Debug and ASan/UBSan standalone CTest builds and
  Windows MSVC/Python native library tests. Speedup is not asserted on
  shared CI runners; sustained hardware throughput is a separate check.

## Streaming and runtime safety coverage

- `tests/test_tiled_raster.py`: per-tile memory/pixel budgets, exact
  geographic tile coverage, cross-tile contiguous polygons, nodata masks,
  temporal gain/loss, partial cancellation and authenticated background jobs.
- `tests/test_vision_runtime.py`: model LRU reuse, preventing active model
  eviction, concurrency caps, release after initialization failure,
  malformed ONNX class/logit validation and tensor budgets.
- `tests/test_spatial.py`: shared-index close/query races and exact
  zero-tolerance fallback lookup.
- `web/e2e/geoai.spec.ts`: full-resolution controls in the user interface.
