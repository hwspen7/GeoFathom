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

## Scientific figure library

Open a Terrain result, choose **Figures**, then **Figure library**. The gallery
shows only recipes supported by the actual result data. Continuous rasters
provide histograms, normalized frequency density, cumulative and exceedance
curves, quantile curves, Tukey boxes and normal Q–Q diagnostics. Classified
products provide class bars and dot plots; aspect provides area-proportional
rose sectors; profiles preserve NoData gaps and support signed grades.
Where a continuous product is aligned with source elevations, the library
also offers elevation/result scatter and two-dimensional frequency maps.

Distribution tables use every finite exported-raster value. Histograms have
10, 20, 40, 80 or 160 numerical bins. CDF curves connect at most 257 exact
cumulative knots. Quantiles use linear order-statistic interpolation; box
whiskers use observed values within 1.5 IQR fences, with outlier counts.
Scatter markers are an explicitly labeled systematic sample of at most
2,000 valid pairs. Joint density and descriptive Pearson correlation use
all valid aligned pairs. Spatial dependence is not used to claim p-values.

Choose frequency, area share or projected area; edit the title and axis
labels, palette, font, grid and applicable logarithmic scales. Save reusable
styles per project. Preview the underlying numeric table before exporting.
CSV headers carry quantity units; JSON includes all plot tables and source,
geometry, parameters, quality and population metadata. Legacy results can
regenerate tables from their recorded input with a source checksum check.
Legacy binned elevation results do not acquire invented exact quantiles.

Exports include SVG, vector PDF, 300/600 DPI PNG with physical-resolution
metadata, CSV, JSON and a self-contained Matplotlib Python script. The script
embeds the selected numerical table and regenerates SVG/PDF/PNG, allowing
further analysis outside GeoFathom. Density curves are normalized frequency
polygons, not fitted KDEs. Plot products are descriptive and retain the
source DEM's validation limits.

### Experiment figures

Each continuous scenario, signed residual, and uncertainty map carries its own numerical plot tables. Open Research analysis → Figures → select a map → Open scientific figure library. The same editable gallery and SVG, vector PDF, high-resolution PNG, CSV, JSON and Python exports are used without rerunning the experiment. Signed residuals additionally expose paired baseline/candidate scatter with a 1:1 reference and all-cell joint frequency counts; circular and nominal quantities do not receive linear agreement statistics. The research ZIP contains `figure-tables.json` and, for Monte Carlo, `uncertainty-realizations.csv` with the actual scalar realizations. These distributions and agreement measures are descriptive, not independent accuracy validation.

The experiment Figures page also exposes a multi-map matrix and a metric figure library. Choose any recorded metric and scenario values, absolute or relative changes, numeric parameter responses, baseline secants, conditional model intervals, or the actual realization distribution. Incompatible or undefined observations remain missing rather than being replaced by zeros. All use the same figure controls and exports.

### Paired and multi-scenario statistics

The paired diagnostic gallery uses a square, shared-scale baseline/candidate plot, a full-population least-squares fit (where the predictor varies), and a Bland–Altman mean/difference plot with descriptive mean and ±1.96 sample standard deviations. Point markers are a bounded systematic sample; estimates use all common cells, and no p-values or independent accuracy claims are made. Compatible continuous scenarios additionally offer grouped Tukey boxes and overlaid empirical cumulative curves; each curve describes its own valid population.

### Two-factor sensitivity

Optionally select a second active numeric sweep parameter and two to four distinct values on each axis. The engine validates all combinations and evaluates the full Cartesian grid using the production operation, subject to the existing cell-evaluation budget. Select Research analysis → Figures → Scientific metric figures → Two-factor response heatmap. Every cell is an actual calculated metric, and unmatched populations remain N/A. Axes show the actual parameter settings as discrete design levels. The ZIP contains factorial.csv, all run receipts, source products, and the report. This is a bounded factorial experiment, not Sobol variance attribution.

## Extended scientific figure studio

The Figure studio button in Terrain, Extended figure studio in the original
figure library, and the completed Research analysis Figures page open the
data-driven extended studio. The 24 existing terrain recipes remain
available; the extended catalog provides 51 additional recipes (75 total
catalog entries, with some related plot families sharing numerical methods).
Select an actual CSV or GeoTIFF dataset, bind the required columns or select
the rasters in order, render a preview, then export PNG (300/600 DPI), SVG,
PDF, TIFF, computed CSV or reproduction JSON. Source hashes, input/used
population, assumptions and exact settings are preserved. The reproduction
JSON embeds inputs; resubmit its input object to POST /terrain/studio/render
with compatible software. Large inputs and invalid numerical designs fail
explicitly rather than silently truncating data.

The extended studio supports multivariate statistics, violin/KDE, Pearson
matrices, regression diagnostics, Pareto dominance, parallel coordinates,
radar, ranking, tornado, Sobol and Morris estimators, actual two-factor
surfaces, regular time-series summaries, cartographic and ensemble maps,
hypsometry and 3D visualization. Sobol and Morris require correctly designed
evaluation tables; the studio does not generate their experiment designs
or run a global terrain model automatically. Tornado requires measured
low/high parameter responses. Conditional significant-change maps require
a supplied difference standard deviation raster. Profile uncertainty
bands require actual lower and upper bounds. Maps use aligned north-up
GeoTIFFs, and terrain derivative operations require projected metre grids
with declared metre elevations. The map north arrow indicates grid north.
Only the 3D rendering is decimated; the source grid remains unchanged.
The older terrain-engine outputs and experiments retain their own
independent scientific validation limits.

The raster input panel also has **Use actual raster cells as table**.
It exports aligned cell-center coordinates and actual quantities from the
common mask. Tables of at most 20,000 cells are exact; larger grids use
every kth common cell in row-major order with explicit population size,
sample size, stride, source checksums and CRS. These sampled tables are
not claimed to be exact all-cell population statistics. The original
terrain gallery remains the path for exact all-cell distributions.
Research experiments also supply named response, factorial, actual Monte
Carlo realization and coverage-interval tables directly to the studio.

## Publication figure refinement

The extended studio now contains 52 recipes (76 including the original 24), with response heatmap, filled/line contours and 3D views under the same response recipe. All views preserve evaluated coordinates and missing cells; contours and 3D interpolate visually only within complete grid cells. Observed extrema can be marked. Profile mode supports distance-aligned overlays, differences from the first series, ordered mean/lower/upper triples and a raster transect recipe using supplied projected path coordinates. Raster transects sample the native pixel at each supplied coordinate, not an invented dense path. Missing samples break the curves. Aligned map matrices support shared ranges, symmetric diverging scales, categorical codes, explicit class breaks, common mask and selectable column count. Grids must be aligned before comparison.

Add any completed extended studio figure to Figure composer, arrange two to six panels, and render one figure with real Matplotlib subfigures, title, caption, panel labels and spacing. SVG and PDF retain vector text/lines, while raster map pixels remain raster. PNG and TIFF export use physical dimensions and DPI. Reproduction JSON records each panel's actual inputs and computed table. Legends and scales are shared within supported map matrices, not indiscriminately across different physical quantities. Canvas-bound checks report potential clipping and do not replace a visual publication review. Tests cover numeric gaps, actual raster sampling, response variants, composition pixel determinism and PDF/SVG output.

All extended recipes now emit a common numerical receipt (source family, selected fields, software versions, input/used/omitted counts, derived-table count and canvas bounds). CI renders every registered extended recipe to PNG, SVG and PDF and retains actual PNG review artifacts plus JSON receipts on the scientific gate. Native exact-population plots can be included in the same vector composer through their validated scene and original table; opening Extended figure studio from the native gallery automatically seeds the composition with the selected plot. Global sensitivity designs and regular time series reject missing observations rather than silently dropping design rows. Parallel coordinates use a continuous color legend for the last selected normalized metric.

### Domain expansion

The catalog now distinguishes 36 basic/quick recipes (24 native result-aware recipes plus 12 general table recipes) and 168 professional studio recipes. The 180-entry studio has a tier selector, domain categories, and search. The additional domain implementations compute spatial lag statistics, reflectance indices, raster spectral PCA, terrain derivatives, land-cover transitions and patches, ensemble summaries, spatial changes, spectral signatures, hydrological curves, environmental and temporal summaries, classification/validation metrics, multivariate statistics, and observed multiobjective dominance. Domain methods declare required input bindings and preserve data provenance through the existing studio pipeline. These are bounded methods, not automatic end-to-end remote-sensing, hydrological, GeoAI, or climate modeling workflows. SHAP plots require supplied contributions; spatial association statistics are descriptive, not significance maps; spectral recipes require aligned calibrated reflectance bands. Input path, resolution, units, and model assumptions remain the user's responsibility. Every new recipe is included in the actual render test matrix.

### Depth and reproducibility

Research analysis includes a Global sensitivity page. Bounded Sobol and Morris designs run the actual selected terrain operation, compare identical valid raster populations, record source checksums, and export the full evaluated design and a plot-ready table. Independent uniform bounds are assumed; Sobol uses paired Monte Carlo sampling and bootstrap intervals, and small designs are screening estimates. The studio's local Moran recipe optionally computes conditional randomization p-values, BY-adjusted p-values and cluster classes, subject to exchangeability and a bounded computational budget. A user-selected numerical GeoTIFF export preserves the computed native grid and full floating-point precision for compatible single-band map recipes. Results can be reused as inputs within the studio without reconstructing numbers from a PNG. The full catalog remains 204 recipes. These methods require independent real-world validation before making scientific accuracy claims.

The studio also accepts individually selected bands from multi-band GeoTIFFs, applies recorded scale/offset before numerical analysis, records band indices with source hashes, and exposes a source inspection panel for CSV missingness, raster dimensions, CRS, valid pixels and exact alignment. Aligned raster-to-table conversion can now combine different physical quantities (for example elevation and slope) while arithmetic raster comparisons still require identical units. Strict JSON serialization is checked for every extended recipe in its actual render test.

The catalog now contains 40 basic figures (24 native and 16 table figures) and 168 professional recipes. The new basic figures calculate rank-size, Lorenz share/Gini, baseline indices and group mean/sample SD from observations.

Ordinary kriging has bounded explicit NoData prediction and conditional SD outputs; observed cells are preserved, and extrapolation is distance-limited. Spatial regression supports an exact metric buffer excluding nearby training observations from held-out folds.

Global research now also supports a two-objective bounded adaptive Pareto search. Actual terrain evaluations explore a seeded Latin hypercube, then refine neighborhoods of nondominated solutions. Both metrics are minimized; full evaluated parameter and response tables and a plot-ready Pareto table are preserved. This is a budgeted observed-front search, not a certified global optimizer.

Publication rendering now tries bounded typography adjustments while preserving numerical data and page dimensions, records all layout attempts and freezes the final Agg layout before export. A preflight failure is reported, not hidden or treated as visual approval. The native 24-recipe test matrix additionally checks finite geometry and numerical table output across three palettes; the studio matrix covers 184 recipes and PNG/SVG/PDF physical and numerical consistency.
