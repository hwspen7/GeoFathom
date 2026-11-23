# Terrain research acceptance ledger

This is a *verification ledger*, not a completion certificate. Each of the 28
analysis tools must independently score at least 95/100 against the agreed
acceptance rubric, and no blocking correctness or data-integrity issue may remain.

## Research modules and remaining verification

| Module | Implemented capability | Remaining scientific verification |
| --- | --- | --- |
| Core workflow | Discoverable 28-operation catalog, explicit method manifests, bounded API parameters and immutable run receipts | Cross-version run reproducibility and diverse input datasets |
| Terrain derivatives | Horn and Zevenbergen–Thorne derivatives, fitted 3×3–9×9 quadratic curvature, TRI/TPI and hillshade | Derivative error sensitivity against measured DEM uncertainty |
| Hydrology | D8/MFD and D-infinity fractional routing, Strahler/Shreve order, priority-flood filling and bounded channel breaching | Complex real-catchment comparison and calibrated input elevations |
| Visibility | Observer FOV, DSM blockers, curvature/refraction, multiple observers and bounded exact candidate coverage | Independently measured visibility and DSM completeness |
| Engineering | Grade-constrained quadratic design, cut/fill uncertainty and weighted suitability surfaces | Surveyed design references and sensitivity calibration |
| 3D terrain | NoData-safe mesh, streaming source windows, camera-prioritized LOD and bounded tile caching | Large-scene GPU performance and complete scientific-result draping |
| Research outputs | Coverage, NoData, datum and uncertainty flags, charts, CSV, GeoTIFF and input provenance | Independent reproducibility across representative regions |

## 95/100 acceptance rule (per tool)

- Mathematics and independent numerical benchmark: **30 points**
- Scientific method and parameter choice: **15 points**
- Reproducible multi-view results and export: **20 points**
- Scaling, cancellation, failure recovery: **15 points**
- Full input/source/algorithm provenance: **10 points**
- Usability and full browser workflow: **10 points**

A mark is earned only with test evidence. A green workflow is necessary but
not sufficient: synthetic unit tests cannot establish absolute survey
accuracy or externally validated scientific conclusions. The
`quality.reference_validation=not_performed` marker must remain visible
until a real independent comparison is executed. Do not replace this with a
fabricated 9.5 score.

## Data semantics

- The original physical GeoTIFF remains continuous float values; legends
  and class plots are visualization categories only.
- TRI/TPI neighborhood radius is measured in cells; 3x3, 5x5, 7x7 and
  9x9 calculations exclude incomplete NoData neighborhoods.
- The four-direction hillshade is the arithmetic mean of four local
  illumination vectors, **not** cast shadows.
- A selected viewshed sector excludes other directions as *out of scope*;
  it does not infer physical visibility outside the sector.
- Shreve channel magnitude sums headwater contributions; Strahler order
  increments only at a confluence of matching highest orders.
- Route model `distance` uses planar step distance; `surface` and
  `gentle` apply explicitly defined nonlinear slope penalties.
- Grid-area results use planar projected cell area, not audited cadastral
  or independently surveyed surface area.

## Repeatable checks

```powershell
cd E:\Personal_Project\GeoFathom
.\Test-GeoFathom-Full.bat
```

Use repository GitHub Actions (Checks, native, Windows, release, memory,
browser) plus real local GIS tasks. Perform benchmark comparisons with
independent validated DEMs before assigning 95/100 to any module.
