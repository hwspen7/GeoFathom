# Research-grade terrain screening: methods and limitations

GeoFathom Terrain → Study supports reproducible multicriteria GIS suitability
analysis. This is exploratory research, not calibrated event risk, survey
certification or engineering design.

## Numerical model

Primary grid: projected, north-up, meter-based DEM with a selected WGS84 study
polygon. Every factor is aligned to its grid; bilinear interpolation may be
used for continuous factors, whereas categorical data must use nearest
neighbor. Only cells with all factors present and all constraints satisfied
are eligible. Missing cells are never replaced by zero. User-specified
anchors (low < high) define increasing, decreasing or triangular target
utility functions that map original values to the interval [0,1].
The total score is a positive-weight normalized linear combination of these
utilities. The score threshold and all factor anchors are explicit inputs,
not dynamically inferred from local min/max.

AHP can replace manual weights with the dominant eigenvector of a finite,
positive, reciprocal comparison matrix. The associated consistency ratio
is computed and a value above 0.10 is rejected. Expert pairwise comparisons
remain subjective and may reflect correlated or redundant criteria.

One-at-a-time sensitivity shifts each weight by plus/minus an explicit
fraction, renormalizes all weights, and recalculates area above threshold
and mean score. This is not a Sobol or global variance decomposition.

Monte Carlo uncertainty supports 0–256 seeded runs, independent Gaussian
per-cell input error in original raster units, and independently perturbed
positive factor weights. Outputs are mean score, sample standard deviation
and threshold exceedance frequency. **Exceedance frequency is not a
calibrated probability of actual field success, and these are not statistical
confidence intervals.** Spatially correlated input errors and uncertainty
in hard-constraint boundaries are not modeled here.

## Independent checks

For elevations, upload a checkpoint CSV whose columns are precisely:
longitude,latitude,elevation_m. The backend reports bias, RMSE, MAE,
median error, NMAD and empirical p95 absolute error. Five or more usable
checkpoints are required. The user is responsible for the independence
of measured checkpoints, compatible epochs, land cover and vertical datum.
Matching datum labels alone do not prove control.

## Research archive and replay

The ZIP contains canonical analysis.json with exact model inputs, AHP,
uncertainty, spatial extent and metrics; aligned input GeoTIFFs actually
used by the calculation; a binary eligible mask raster; all derived
float32 GeoTIFFs; and a SHA-256 manifest with byte sizes for every member.
Stable ordering and timestamps make identical runs reproducible across
executions of the same software stack.

POST /terrain/research/verify checks content integrity.
POST /terrain/research/replay recomputes all output rasters from archived
aligned inputs and rejects deviations beyond float32 output precision.
The archive includes aligned study data, not complete original acquisition
sources, whose checksums remain recorded. Thus numerical replay does not
independently reproduce remote data acquisition or georeferencing decisions.

Safety limits: 2–8 factors, at most 1,000,000 selected grid pixels per run,
0–256 Monte Carlo draws, 120 MB maximum uncompressed archive verification.
Split larger study areas rather than silently lowering native source quality.

These capabilities do not automatically generate road, weather, demographic
or land-use input rasters. Those must be acquired, checked and prepared
independently. Additional future research capabilities include spatially
correlated uncertainty, multi-criteria vector rasterization, calibrated
probabilistic risk, global Sobol sensitivity and project-level collaborative
scientific repositories.

## Acceptance

Tests must cover analytical cell scores, exact AHP reciprocal matrices,
inconsistent weights, NoData, hard constraints, grid alignment, deterministic
ensembles, SHA-256 tamper detection, verified and forged archives, independent
GCP diagnostics, and API-level managed imagery identifiers. CI success on
synthetic fixtures is not independent cross-software scientific verification.
Before publication, compare selected real-area outputs with QGIS/GRASS and
inspect original source survey metadata.

Method references:
- https://www.usgs.gov/ngp-standards-and-specifications/3d-elevation-program-standards-and-specifications
- https://www.ogc.org/standards/stac/
- https://doi.org/10.1016/J.CAGEO.2013.11.009
