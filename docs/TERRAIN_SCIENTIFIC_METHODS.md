# scientific methods scientific-engine maturity and acceptance ledger

This file records the delivered algorithms and the evidence required to claim
95/100 per professional analysis tool. **Synthetic unit tests and green CI are
not a survey, field accuracy, or full professional certification.** See also
[TERRAIN_RESEARCH_ACCEPTANCE.md](TERRAIN_RESEARCH_ACCEPTANCE.md).

## Mathematical / execution implementations

| Area | Implemented numerical behavior | Limits that still block unconditional 95/100 |
| --- | --- | --- |
| Hydrology | Eight-triangle D-infinity downslope routing on a metric projected grid, fractional two-receiver flow, explicit externally provided cell-equivalent upstream inflow, NoData diagonal-corner exclusion, deterministic high-to-low processing, optional bounded least-cut channel breaching, existing priority-flood filling and finite flat routing | A controlled independent PySheds D-infinity cardinal-plane comparison is added; complex real-basin TauDEM/GRASS topology agreement remains unverified. Breaching is bounded **approximate least-cost excavation**, not a global minimum-cut earthworks design. Does not infer unknown off-grid inflow |
| Curvature | 3×3–9×9 centered least-squares quadratic fit with normalized coordinates, analytic second derivatives, explicit NoData gaps and undefined directional curvature on flat terrain | No independently published external curvature tolerance suite; physically biased data need vertical error analysis |
| Viewshed | Co-registered DSM blocker elevation alongside bare-earth observer/target heights, unknown-ray masks, refraction/curvature, **exhaustive maximum-coverage selection** of up to four sites from 12 candidates, with a checkable finite-search audit | Exactness applies only to supplied candidates, not all geographic positions; ray count remains bounded at 100 million and 10 km; no verified DSM inventory |
| Engineering | Grade-constrained quadratic design surface (including optional east/north/cross curvature) and cut/fill, conservative whole-grid maximum grade, conditional Gaussian independent-cell cut/fill intervals and exact correlated normal datum-offset quantiles; weighted suitability utility from slope, TRI and middle-of-band elevation with hard exclusions, normalized weights, continuous GeoTIFF score | Not a fully unconstrained CAD-designed surface, geotechnical model, surveyed volumetric computation, calibrated stochastic uncertainty distribution or GIS MCDA validation. Scores are **not probabilities** |
| 3D | Seam-aligned 32-cell source windows, camera-prioritized and relief-aware LOD, source-pixel NoData testing, **measured maximum and RMSE vertical TIN approximation errors** (metres) per tile, bounded parallel cancellable requests, access-ordered GPU cache, WebGL2 mesh and preview OBJ export | Visual LOD curvature is only a heuristic; returned tile error is measured. Not a seam-morphed global quadtree; OBJ exports the preview, and research rasters are not automatically draped. |

## Semantics and reproducibility

- Existing 28 Terrain operation IDs remain available; new scientific methods algorithms are
  method selections inside the existing operations.
- The original DEM is immutable; hydrological conditioning, DSM occlusion,
  grade planes and calculated scores operate on separate working arrays.
- D-infinity accumulation includes one cell-equivalent for each valid study
  cell plus exactly the external raster's provided positive inlet values;
  off-grid catchments are not otherwise inferred.
- External inflow must have the identical projected grid, complete values
  wherever the DEM is valid, and the GeoTIFF tag
  \`TERRAIN_UNIT=cells\` or \`TERRAIN_UNIT=cell_equivalents\`.
- DSM must be co-registered; NoData blocker rays are unknown, not invisible.
- Quadratic curvature uses complete neighborhoods only. Its differential
  curvature values are inverse metres, not grades.
- Weighted suitability uses scores in [0,1], with a hard exclusion score of
  zero; empty/no-derivative cells are NoData. The score is neither probability
  nor a statistically calibrated suitability certainty.
- Quadratic engineering design grades are bounded on the full study-grid
  rectangle (a conservative bound for an irregular selected polygon).
- Gaussian cut/fill expectations and variance use closed-form truncated
  normal moments. Independent-cell cut/fill 95% intervals are normal
  approximations; net volume is exactly Gaussian under the assumption.
  Fully correlated normal datum-offset quantiles are reported separately.
  No model is a field-calibrated confidence interval without measured sigma.
- Camera-dependent source-resolution tile requests read only each DEM
  window; reported TIN vertical residuals compare source pixels in
  complete quads to the actual two WebGL triangles. Invalid quads never
  contribute false zero errors. The request queue is cancellable and
  concurrency-bounded with an access-ordered GPU cache. The
  initial preview mesh stays fully resident so streaming refines it rather
  than removing all base geometry from GPU memory.

## Acceptance evidence

Mandatory minimum before calling any operation **95/100**:

1. **Mathematical correctness (30):** independent analytic fixtures,
   cross-implementation tests (e.g., TauDEM, GRASS, GDAL), bounded numerical
   residuals, difficult NoData/flat/basin cases.
2. **Scientific models and parameters (15):** documented parameter ranges,
   honest units, unbiased data semantics and scientifically meaningful choices.
3. **Reproducibility and exports (20):** source hash, original grid and source
   datum, immutable run receipt, precise GeoTIFF and data/figure exports.
4. **Scalability and cancellation (15):** representative worldwide DEM
   benchmarks, CPU/memory budgets, cancellation, failure isolation, realistic
   large viewsheds and 3D streaming.
5. **Input/source/algorithm provenance (10):** exact method and parameters,
   explicit datum and quality markers, source identity and upstream inlets.
6. **Full browser usability (10):** operation-selectable parameter controls,
   execution, inspectable results, regression with screenshots and saved run.

Each category needs direct evidence; the project cannot raise a score merely
by adding test names. The foundation gate's **synthetic 95+ score is not a scientific methods
scientific certificate**. scientific methods currently records
\`reference_validation=not_performed\` in individual run receipts pending
independent reference validation.

## Automated tests

- \`tests/test_terrain_scientific_methods.py\`: analytic D-infinity, external inflow,
  corner NoData and invariants, fitted polynomial curvature and large windows,
  designed grade and uncertainty, DSM blockers, multi-observer optimization,
  weighted suitability GeoTIFF, LOD boundary continuity, and bounded breach.
- \`web/src/terrainMethods.test.ts\`: algorithm-specific run identity and source
  provenance, no unrelated parameter contamination.
- \`web/src/terrainLOD.test.ts\`: camera mesh LOD node indices, boundary
  cells and NoData face exclusion.
- \`.github/workflows/terrain-science.yml\`: existing independent-GDAL foundation
  reference gate plus an additional, mandatory scientific methods analytic/GeoTIFF test step.
- The repository's full Python, TypeScript, native, browser, memory and release
  suites remain mandatory prior to merging.

**Current release state:** work in progress. Branch
\`current scientific-methods branch\` and PR #9 are intentionally separate from
\`main\`; release readiness requires fresh green checks at the exact head SHA.
