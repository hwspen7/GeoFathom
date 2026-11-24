# Scientific Figure Studio — research publication refinement

Extends the existing gallery instead of replacing established Terrain, Spatial Analysis, Remote Sensing, Network and Spatiotemporal figure sources.

## New native research figures
Paired validation/Bland–Altman, ECDF, paired empirical QQ, supplied-interval forest, centered Taylor comparison with centered-error contours, nested supplied prediction intervals, paired space-time lag semivariance/support matrices, native raster map plus histogram, aligned map agreement, bivariate tertile map and common-mask change atlas. They use recorded inputs and never synthesize missing data. Agreement statistics are descriptive, not a causal or confidence claim. Raster units/grid alignment are checked; bivariate maps permit distinct quantities. Semivariance bins retain physical lag spacing and missing bins.

## Composition
Up to 12 independently rendered panels on one native Matplotlib canvas, optional caption row, weighted row/column sizes and validated rectangular spans. Equal grid, full-width lead and custom slots in the workbench. Overlapping/out-of-bounds/undersized slots are rejected; final visual review remains necessary. Vector output retains vector plot primitives and text; actual raster images remain embedded raster data.

## Map controls
Sequential palettes, explicit physical color limits for continuous maps and zero-centered diverging scales. Out-of-range cell counts and colorbar extensions are recorded. Native source values remain unchanged. Grid/minimal decoration applies to supported map recipes; projected scale bars represent grid distance, not necessarily exact ground geodesic distance.

## Archive
Research archive ZIP contains rendered PDF, embedded original CSV/GeoTIFF inputs in reproduction.json, derived figure/panel CSV where available, metadata, SHA-256 and size manifest. Open reproduction.json in the Studio to restore a single figure or composition. Re-rendering can differ across software/font versions; hash verifies archive contents, not numerical truth. No external paths or code are executed.

## Acceptance
Run python -m pytest -q tests/test_studio_publication_research.py . Mandatory per-recipe references render actual PNG, SVG and PDF, test analytical metrics, missing bins, layout overlap, a twelve-panel composition, source hashes, archive roundtrip and fixed display ranges. Full repository and browser regression must pass before release. No claim of complete test execution is made here.
