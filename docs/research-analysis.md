# Terrain research analysis

Run a Terrain analysis, select its result, and open **Research analysis**.
The Experiment, Results, Figures and Report pages keep experiments separate
from the compact map docks. Completed experiments are restored per project;
download the research package for a portable record.

## Named scenarios and spatial differences

Create up to eight named alternatives. Each alternative can change several
parameters of the selected operation. Source DEM, operation, exact study
geometry and grid are held fixed. For example, compare Horn and
Zevenbergen–Thorne slopes, D8 and D-infinity accumulation, two illumination
models, or several design surfaces. Inactive parameters and unknown fields
are rejected.

Results show every common numerical metric, signed and relative changes,
and pixel maps on the common valid population. Difference signs are
**candidate minus baseline**. Nominal classes use transition counts and a
changed/unchanged raster. Aspect changes use the shortest signed circular
angle, excluding flat cells. Incompatible units or grids fail explicitly.
If output masks differ, aggregate changes and response slopes for those
populations are disabled. Common-cell differences remain available with
coverage counts. A zero baseline has no relative percentage.

The Figures page supports baseline/scenario swipes, individual outputs,
GeoTIFF downloads and publication of a selected raster to the map.
Continuous products with adaptive source legends share one numerical
preview range across scenarios. Signed differences use a zero-centered
palette; original GeoTIFF quantities are retained.

## Parameter sensitivity

Choose one numeric parameter and supply two to eight distinct values.
The engine reruns the production operation for each value. Curves show
actual responses; reported slopes are secants from the baseline:

`(response(value) - response(baseline)) / (value - baseline)`.

A zero step has no slope. Discrete parameters require integers. Parameters
must affect the operation: curvature radius requires the quadratic method,
and refraction requires Earth curvature correction. These sweeps do not
estimate interactions or global variance-based sensitivity indices.

## Uncertainty propagation

Specify an assumed DEM vertical standard deviation, spatial error model,
seed, realization count and coverage probability. Supported models are
independent Gaussian cell errors and one common Gaussian vertical offset.
The original DEM remains unchanged. Each realization reruns the production
surface or earthwork calculation, preserving source NoData.

Outputs contain metric means, sample standard deviations, equal-tail
model coverage intervals, Monte Carlo mean standard errors, and split-half
endpoint differences as a numerical stability diagnostic. Raster products
include pointwise mean, standard deviation and lower/upper bounds, retaining
only cells valid in every realization. The implementation uses seeded PCG64,
linear empirical quantiles, and sample standard deviation (`ddof=1`).

These intervals are conditional on the supplied error model. They are not
independently measured accuracy, confidence intervals of the mean, or
simultaneous spatial bounds. Twenty to five hundred trials are supported;
tail precision depends on trial count and is not certified as converged.
Spatial correlation between the independent and common-offset extremes,
horizontal errors, and uncertain masks require additional input models.
Set the separate analytic earthwork sigma to zero before an outer Monte
Carlo experiment to avoid stacking error models.

The experiment window is bounded to 2,000,000 cells and repeated evaluation
to 12,000,000 cell realizations. Requests use cooperative cancellation and
temporary perturbed rasters are cleaned up on completion or cancellation.

## Research package and reproduction

The downloadable ZIP includes:

- `report.pdf`: maps, response figures, all validated parameters, tables,
  data quality, source metadata and limitations.
- `experiment.json`: complete validated request, exact WGS84 geometry and
  source/dependency SHA-256 checksums.
- `manifest.json`: runtime versions, projected grid transform, scenario
  receipts, output inventory, uncertainty model and quality information.
- `metrics.csv`, with sensitivity/uncertainty CSVs when applicable.
- Every available GeoTIFF and its georeferenced map-preview PNG.

Submit `experiment.json` to `POST /terrain/research/analyze` to rerun the
experiment with its original source assets available. Changed source or
auxiliary raster bytes are rejected. `GET /terrain/research/catalog`
provides supported operations, parameter choices and sweep parameters.
Use the same software revision and numerical dependencies when reproducing
numerical results; generated timestamps and PDF metadata are not bitwise
reproducibility targets.

Method reference: [JCGM 101:2008, propagation of distributions using a Monte
Carlo method](https://doi.org/10.59161/JCGM101-2008). The finite-trial stability
checks do not claim full JCGM conformance or adaptive numerical convergence.
