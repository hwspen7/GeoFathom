# Terrain P0–P6 research acceptance ledger

This is a *verification ledger*, not a completion certificate. Each of the 28
analysis tools must independently score at least 95/100 against the agreed
acceptance rubric, and no blocking correctness or data-integrity issue may remain.

## Stage delivery and remaining verification

| Stage | Implemented in this upgrade | Not yet certified or completed |
| --- | --- | --- |
| P0 | Discoverable 28-operation catalog; explicit method manifests and API bounds; existing immutable run receipts | A third-party dynamically loadable plugin runtime and formal versioned method migration |
| P1 | Horn/Zevenbergen–Thorne in summary, small/large surface grids; variable 3×3–9×9 TRI/TPI; single/four-direction hillshade; classification presets | Independent GDAL/GRASS cross-reference and uncertainty envelopes for all derivatives |
| P2 | D8/MFD, bounded MFD exponent, deterministic conditioning; true Strahler and Shreve alternatives | D-infinity, surveyed stream calibration, full external upstream contributing area |
| P3 | Single/multi-observer viewsheds with curvature/refraction, observer azimuth, field of view, distance cap | Independent line-of-sight reference suite, large-area optimized rays and DSM inventory accuracy |
| P4 | Multiple route cost functions; existing volume, cross sections, DEM comparison and suitability | Designed engineering surfaces, stochastic uncertainties and external design-level calibration |
| P5 | Selectable 64–512 mesh budget, existing WebGL terrain and optional imagery drape | Streaming 3D LOD and guaranteed 3D analysis scalability |
| P6 | Explicit coverage/NoData/datum/uncertainty status; quantitative distribution, chart mode, class area table and CSV; output provenance | External scientific benchmark set, complete portable project package, performance verification across all algorithm combinations |

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
