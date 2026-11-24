# Terrain research choices and multidimensional results

GeoFathom Terrain supports **scientific method choices**, **separate display choices**
and **reproducible result artifacts**. A display change never rewrites the physical
values in the original derived GeoTIFF.

## Scientific parameters

| Operation | Input choice | Bounds and interpretation |
| --- | --- | --- |
| Slope map | Horn or Zevenbergen–Thorne | 3 × 3 weighted gradient versus cardinal-neighbor central difference |
| Aspect, hillshade, curvature, plan/profile curvature, suitability | Horn or Zevenbergen–Thorne | The gradient selection is also used for directional derivatives and hillshade; TRI/TPI do not need a gradient choice |
| Slope map | Standard / detailed / broad classes | 6 / 8 / 4 ordered bins. Classification only affects map colors and the class histogram |
| MFD accumulation | Convergence exponent | A real float from 0.5 to 8.0; greater exponent weights steeper downhill receivers more strongly |

All method selections are validated at the API boundary, passed through the
actual Python computation and included in the operation-specific input manifest.
Changing an applicable scientific option changes the run identity; unrelated
controls do not invalidate prior results. The operation's validated parameters
and source identity are included in the run's locally persisted receipt.

The default gradient algorithm remains Horn. Existing projects are compatible
with the default standard slope classes and MFD exponent 1.1.

## Results to inspect

**Overview** shows operation-specific physical metrics plus valid derivative
cell coverage and total classified projected-grid area where applicable.

**Figures** provides an operation-dependent collection of views:
- Analysis: raster preview and class histogram, with user-selected **valid cells,
  share of valid classified cells (%) or projected grid area (km²)**.
- Composition: proportional distribution of classes, not an estimate of
  ground-truth probabilities.
- Cumulative: per-class share bars and cumulative valid-area share in **ordered**
  numerical class order. Directional/aspect and unordered categories do not
  offer this curve.
- Other relevant outputs: elevation hypsometry, profile grades, aspect rose,
  measured sections and 3D terrain.

**Data** exposes source/acquisition, declared vertical datum, actual input
parameters, validity warnings, all scientific metrics (including standard
deviation and P10/P50/P90 for continuous raster products), class totals,
GeoTIFF and a per-class CSV.

The CSV contains **class, cells, share of classified valid cells,
projected-grid area (m²), cumulative share (%) and cumulative area (m²)**.
Areas use the projected raster's cell area, not a separately surveyed/geodesic
land-area measurement. Class percentages exclude NoData and unclassified cells.

## Validation

- `tests/test_terrain_professional.py`: planar gradient parity, a patterned
  raster that distinguishes the two gradients, 4/6/8 classification, unchanged
  physical float GeoTIFF and NoData preservation.
- `tests/test_terrain_advanced.py`: algorithm options and percentiles from
  a georeferenced DEM, with GeoTIFF integrity.
- `tests/test_terrain_multiflow.py`: MFD exponent materially changes a
  branching-flow fixture and survives the persisted engine output.
- `web/src/terrainRunParameters.test.ts` and
  `web/src/terrain-charts.test.ts`: input identity, area percentages, CSV.
- `web/e2e/terrain-workbench.spec.ts`: interactive parameter selection,
  cumulative plot, chart measure choice, class table and CSV download.

The tests establish contract and synthetic numerical correctness for these
choices; they **do not** certify actual DEM survey accuracy, universal
agreement with independent GIS implementations or hydrological engineering
design suitability. Validate native DEM resolution, vertical datum, study-area
completeness and reference GIS outputs before publication.

## Extending the option set

For a new scientific method, add a numerical implementation with an independent
test fixture, validate the API input, expose its TypeScript option, include it
in `terrainParametersForOperation` only for applicable tools, and add an
operation-aware result view and browser regression. Do not make a display-only
selector appear to alter the underlying scientific calculation.

A general algorithm plugin registry and fully tiled processing for every
advanced operation are separate future architecture work. This iteration adds
user-selectable methods to existing validated execution paths; it does not
pretend the entire engine is already plugin-driven.
