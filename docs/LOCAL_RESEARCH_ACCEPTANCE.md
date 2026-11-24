# GeoFathom · local scientific acceptance (Windows)

This is the **research-use** validation protocol for surveying surveying, terrain analysis terrain science,
bounded compute bounded compute and the reusable workspace. It is not a legal cadastral survey,
independent terrain truth dataset or enterprise load certification.

## One-click entry points

Run from the checked-out `feature/terrain-professional-analysis` branch:

| File | Purpose | Starts its own API/Web server? |
| --- | --- | --- |
| `Start-GeoFathom.bat` | Install missing local dependencies, launch API/Vite in separate consoles, open `http://127.0.0.1:5173` | Yes, for interactive use |
| `Test-Terrain-Quick.bat` | Numerical Python Terrain tests, frontend build/unit tests, real-browser Terrain and project isolation | Yes, temporary isolated Playwright servers |
| `Test-GeoFathom-Full.bat` | MSVC C++ CTest, full Python tests using native DLL, frontend build/unit, all browser E2E serial and four workers | Yes, temporary isolated Playwright servers |

Requirements: **Windows PowerShell 5.1+**, Python **3.11+**, Node.js **22+**
(20+ works for app, but CI uses Node 22); `npm` and `npx` on PATH.
Full testing additionally requires CMake and Visual Studio/MSVC C++ build tools.
Optional local CUDA/RTX hardware is a separate qualification and is *not* required
for the research workbench, though `scripts/Hardware-Acceptance.ps1` exists.

The launchers use a repository-local `.venv` and `npm ci`; they do **not**
modify or delete the existing project database. Browser acceptance uses
`data/e2e-geofathom-local-serial.sqlite` and
`data/e2e-geofathom-local-parallel.sqlite`, separately from
`data/geofathom.sqlite`. **Do not run browser acceptance while the interactive
app is open:** ports 8000 and 5173 must be available. The one-click script
fails instead of reusing a live project. Close both dedicated server consoles
before clicking either test launcher.

Console transcript: `data/local-acceptance/acceptance-*.txt`. Browser
failure screenshots and traces: `web/test-results/`. Any failed stage makes
the launcher exit unsuccessfully; none of these reports is a substitute for
inspecting numeric geospatial outputs.

## Interactive surveying and terrain analysis verification

1. Start GeoFathom and create a distinct research test project (e.g.,
   `OSU terrain acceptance`). Do not overwrite an existing research workspace.
2. Search for `The Ohio State University`; select the campus footprint, not
   a building or only a search-point location. Confirm the display indicates
   the **actual geometry source**, geographic bounds and editable vertices.
3. Drag at least one boundary vertex, add a vertex or refine a segment, Undo,
   Redo; verify all maps, area/perimeter values and object tree reflect the
   current geometry. Switch between Survey, Terrain, GIS and back: **the
   selected study boundary must remain until manually changed or deleted.**
4. Save the selected polygon. Reload the browser, select the saved object and
   verify geometry, name, source and revision survived. Enter another project
   and verify no saved object or undo history leaks across project identities.
5. Open Terrain, acquire a DEM or import an independently obtained referenced
   GeoTIFF. The study target must have valid DEM coverage; chosen output grid
   size cannot be claimed as finer native source accuracy. Confirm source
   provenance, CRS, declared vertical datum, unit, valid/missing coverage and
   no silent selection replacement.
6. Run Elevation, Slope, Aspect, Contours, Hillshade and Elevation profile.
   Inspect numeric ranges, coordinate-linked chart cursor, output raster
   pixel size and NoData. Compare known constant/planar reference DEM values
   against independent calculation, not just an attractive map preview.
7. Run Flow direction, Flow accumulation, MFD accumulation, Drainage network,
   Strahler stream order and Watershed. Verify flow does not teleport across
   NoData corners. Compare a small known synthetic grid with a reference
   Python/QGIS calculation before treating results as published science.
8. Run Visibility and Multi-observer viewshed with **two distinct valid**
   positions. Verify unknown ray paths remain unknown and that visible,
   hidden and unknown totals do not overlap. Run with incomplete inputs to
   check that the Run button is disabled and no invalid result is saved.
9. Run Cut/fill and optionally DEM difference using two genuinely comparable
   rasters; inspect units, source-grid alignment and the warning about
   different CRS/source/geometries. Check inputs before interpreting the
   numerical delta.
10. Test the reusable UI: module navigation, `Ctrl+K` command search,
    searchable per-layer feature tree, show/hide inspector and drag side
    splitters. Check the map stays on-screen after opening a long Terrain
    result. Confirm chart hover updates the map and map hover updates the
    chart, and module switching never clears the study area.
11. Export GeoTIFF separately from the run JSON/GeoJSON. Verify the output
    has input geometry, operation-specific parameters, source identifier and
    hash where available. A saved contour/vector feature must keep provenance
    in the project even after local browser result cache removal.
12. Repeat key cases at Stanford University and an area outside USGS coverage
    to verify global-provider fallback, geographic-source availability and
    honest resolution limitations. Do **not** assert a 3 m DEM exists when the
    upstream provider only supplies 30 m data.

## Acceptance decisions

- **surveying target 95–100%:** editable source geometry, persistence, exact units,
  credible DEM coverage/provenance and reliable basic analysis/export are
  demonstrated on actual sites plus known synthetic standards.
- **terrain analysis target 90–95%:** operations can run from the UI, with explicit
  parameters, meaningful scientific warnings, representative independent
  numerical oracles and portable reproducible outputs.
- **bounded compute target 65–70%:** local machine loads are bounded, cancellation and
  cleanup work, native fallback is honest, and serial plus concurrent
  regression runs pass. Multi-tenant/distributed commercial scaling is
  not required.
- **Workspace:** commands are discoverable, the model/object tree is
  searchable, layout is reusable, selections persist, and keyboard/mouse
  workflows do not interfere with map interaction.

These percentages are **human acceptance judgments**, not code coverage
thresholds. Historic strict CI coverage goals remain separate and must not
be silently disabled or represented as satisfied without evidence.

## Manual commands equivalent to one-click

```powershell
.\Start-GeoFathom.bat
# Close the API and Web windows before running tests:
.\Test-Terrain-Quick.bat
.\Test-GeoFathom-Full.bat
```

Do not run both test launchers simultaneously. For a failing case, retain
the exact failing console step, the transcript and the Playwright screenshot/
trace. Fix and rerun rather than lowering acceptance expectations.
