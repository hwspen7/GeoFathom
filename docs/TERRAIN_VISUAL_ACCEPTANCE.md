# Terrain display and cross-source regression acceptance — 2026-11-22

## Map/profile bidirectional cursor
- Each profile sample is a georeferenced WGS84 coordinate tied to a measured station distance.
- Chart hover selects the corresponding map marker.
- Map hover within 16 screen pixels of the actual projected profile polyline chooses the closest **existing sample** and updates the chart cursor. It cannot synthesize unmeasured heights.
- Moving off the line clears the map-driven cursor; drawing, vertex-editing and point-picking take precedence and suppress the link.
- The independent profile geometry and selected campus boundary remain separate objects.

## Visual hierarchy
- Selected boundaries retain all nodes in source data. At map overview zoom, only a deterministic visual subset of nodes appears; zooming in reveals more; edit mode shows all vertices and midpoints.
- A pale high-lightness slope palette improves legibility without changing slope cutoffs or source GeoTIFF.
- A raster can use nearest display resampling for exact class edges or smoothed display for visual continuity; smoothing **does not increase native DEM resolution**.
- Run-specific raster opacity and display resampling are independent. Newly computed raster layers do not erase older results; toggles can show/hide them separately.

## Provenance and versions
- Each run has an immutable ID, timestamp, source asset ID/name/acquisition, provenance, raster grid dimensions, CRS and geographic footprint.
- A comparison only displays common finite physical summary statistics, not grid cell counts. Warn when geometries or DEM sources differ. Differences are descriptive, not pixel registration or accuracy certificates.
- A lightweight per-project browser-local registry stores up to 100 **metadata receipts only**, with JSON export. Raw rasters and charts remain exportable separately. Browser storage clearing can remove receipts.
- Source data accuracy must still be verified with an independent DEM and documented source resolution; a requested USGS 10 m output grid does not prove native 10 m input resolution.

## Required verification
```powershell
cd E:\Personal_Project\GeoFathom
git fetch origin
git switch feature/terrain-professional-analysis
git pull --ff-only origin feature/terrain-professional-analysis
python -m pytest tests/test_terrain_professional.py tests/test_terrain_advanced.py -q
cd web
npm ci
npm run build
npm test
npx playwright test e2e/terrain-workbench.spec.ts --workers=1
```

For real Stanford 30 m versus 10 m comparison, require geospatially matched study bounds and independently verified metadata. Do not infer a gain in precision from interpolated colors or requested spacing.
