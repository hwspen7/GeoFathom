# Multi-dimensional validation matrix

The tests below are automated against the real code in the repository.
They do not by themselves certify cadastral accuracy, GPU performance or
a production multi-user deployment.

| Area | What is checked | Test location |
| --- | --- | --- |
| Basic spatial geometry | Polygons, holes, line lengths, geodesic WGS84, malformed coordinates | \`tests/test_geometry.py\`, \`tests/test_robustness.py\` |
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

## Other common GIS features worth prioritizing

Features present in QGIS or ArcGIS Pro but not yet fully replicated:

1. **Spatial identify/select tools:** rectangular/lasso selection, multi-
   select and selection by spatial relation (within, intersects, touches).
2. **CRS-aware project view:** choose map projection, coordinate grid and
   transformation policy; antimeridian workflow.
3. **Graduated and rule-based cartography:** numeric classifications,
   field-calculated expressions, per-category visibility and full labeling
   priority/callout/drag-to-position controls.
4. **Professional print layout:** page sizes, legend, scale bar, north
   arrow, attribution, high-resolution PDF/SVG export.
5. **Large project store:** PostGIS, indexed attribute paging, background
   imports and streaming vector/raster tiles.
6. **Data QA:** topological gap/overlap detection, snapping tolerances,
   repair suggestions and data integrity reports.
7. **Sources & services:** WMS, WMTS, WFS, OGC API Features and a more
   configurable local/offline basemap cache.
8. **Tasks:** long-running background GIS operations, GPU scheduling,
   progress/cancel, logs and reproducible job results.

Keep these separate from claims of completed support. The current work is
a reliable next step toward a professional GIS workspace, not a substitute
for a full commercial desktop GIS.
