# Terrain business-logic audit — 2026-11-22

This document defines the acceptance criteria for DEM download and terrain analysis in GeoFathom. It is not a claim that every possible GIS input has been exhaustively verified.

## Invariants
1. Fetch DEM defaults to the current **visible map**. Selecting a polygon never silently changes this scope.
2. The Fetch area selector can explicitly choose a valid selected polygon/line; invalid/point selections must not silently fall back.
3. A dashed amber outline and coordinate readout show the bounding box that will be submitted.
4. The client estimates pixel cost, and the server independently enforces the UTM grid cell budget.
5. The resulting asset's georeferenced footprint must contain the entire requested bbox. Request coordinates must round-trip unchanged.
6. Selecting an existing DEM does not move the map; raster Fit is an explicit action.
7. Searching for a new place outside the DEM clears the active DEM without deleting its source file.
8. A DEM outside the current view or analysis geometry may not be used for a new terrain calculation. Moving away during analysis cancels the request.
9. At most one imported DEM is visible by default. Old analysis results remain in history but are hidden when the source changes.
10. USGS 3DEP downloads must be single-band floating-point elevations with expected grid size and valid CRS. Rendering/visualization raster functions must not replace raw elevations.
11. Cancelled or superseded DEM requests may not reselect a stale source. Remote work observes cooperative cancellation checkpoints.
12. Changes to labeling and symbology must serialize against the server's current style revision; a pending blur operation must not be discarded.

## Regression tests
- `web/src/terrainSource.test.ts`: CMH versus unrelated southern-Ohio polygon; explicit scope; full-footprint verification; coordinate validity; high-resolution budget; large geometry.
- `web/src/rasterLayers.test.ts`: one active DEM; old layer hidden; source reclassified correctly.
- `web/e2e/terrain-workbench.spec.ts`: actual browser source input, target outline, scope selector, analysis, WebGL, exports, clearing DEM.
- `web/e2e/labels.spec.ts`: serial and four-worker cartographic-style persistence; in-flight edits.
- `tests/test_public_dem.py`: Copernicus tile acquisition; USGS image-service data contract, float32/no renderer, grid dimensions, NoData, cancellation, provenance.
- `tests/test_terrain_professional.py`, `tests/test_terrain_advanced.py`: numerical derivatives, D8, route costs, engineering sections, GeoTIFF and angular statistics.

## Commands (from repository root)
```powershell
python -m pytest tests/test_public_dem.py tests/test_terrain_professional.py tests/test_terrain_advanced.py tests/test_terrain_cancellation.py -q
cd web
npm ci
npm run build
npm test
npx playwright install chromium
npm run test:e2e -- terrain-workbench.spec.ts labels.spec.ts
```

## CMH manual scenario
- Search `John Glenn Columbus International Airport` and verify the map is at approximately (longitude -82.892, latitude 39.997).
- If an old raster from about (-82.55, 39.43) is selected, it must be cleared or warned as offscreen.
- In Terrain, select `Current map view`, zoom to the airport, and inspect the displayed request bounds and dashed target rectangle.
- Request USGS 3DEP 10 m, not 1 m for the full airport. Requested grid spacing does not guarantee original source resolution.
- Confirm returned raster coordinates cover the displayed request before running Slope map. A 1 m grid is suitable only for a small sub-area within the 1-million-cell limit.
- Verify output units, nodata masking, GeoTIFF CRS/bounds, chart export, and cancel behavior.

## Honest limitations
- The remote 3DEP endpoint and third-party imagery services require a live network check on the target host. Synthetic/mocked CI cannot establish 3DEP availability or native resolution at CMH.
- D8 routing does not hydrologically condition sinks/flats. Viewshed does not include Earth curvature, vegetation or buildings. Engineering costs and site suitability are screening estimates, not design certification.
- The repository-wide coverage threshold is a separate acceptance gate. Passing functional tests does not imply that all coverage targets are met.
