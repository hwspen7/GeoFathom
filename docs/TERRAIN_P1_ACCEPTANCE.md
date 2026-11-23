# P1 scientific-engine maturity and acceptance ledger

This file records the delivered algorithms and the evidence required to claim
95/100 per professional analysis tool. **Synthetic unit tests and green CI are
not a survey, field accuracy, or full professional certification.** See also
[TERRAIN_P0_P6_ACCEPTANCE.md](TERRAIN_P0_P6_ACCEPTANCE.md).

## Mathematical / execution implementations

| Area | Implemented numerical behavior | Limits that still block unconditional 95/100 |
| --- | --- | --- |
| Hydrology | Eight-triangle D-infinity downslope routing on a metric projected grid, fractional two-receiver flow, explicit externally provided cell-equivalent upstream inflow, NoData diagonal-corner exclusion, deterministic high-to-low processing, optional bounded least-cut channel breaching, existing priority-flood filling and finite flat routing | No independent TauDEM/GRASS basin comparison across catchment topologies. Breaching is bounded **approximate least-cost excavation**, not a global minimum-cut earthworks design. Does not infer unknown off-grid inflow |
| Curvature | 3×3–9×9 centered least-squares quadratic fit with normalized coordinates, analytic second derivatives, explicit NoData gaps and undefined directional curvature on flat terrain | No independently published external curvature tolerance suite; physically biased data need vertical error analysis |
| Viewshed | Co-registered DSM blocker elevation alongside bare-earth observer/target heights, unknown-ray masks, refraction/curvature, greedy selection of up to four sites from at most 12 user candidates | Candidate search is greedy rather than globally optimal; ray count still bounded by 100 million and 10 km local extent; no automatically acquired/verified DSM inventory |
| Engineering | Grade-constrained quadratic design surface (including optional east/north/cross curvature) and cut/fill, conservative whole-grid maximum grade, assumed independent vs fully correlated elevation error bounds; weighted suitability utility from slope, TRI and middle-of-band elevation with hard exclusions, normalized weights, continuous GeoTIFF score | Not a fully unconstrained CAD-designed surface, geotechnical model, surveyed volumetric computation, calibrated stochastic uncertainty distribution or GIS MCDA validation. Scores are **not probabilities** |
| 3D | Seam-aligned 16/32/64-cell tile kernel with power-of-two LOD, a 3-level mesh pyramid in result data, camera-zoom-based index buffers with NoData interior checks, WebGL2 3D preview and OBJ export | This is **preloaded adaptive LOD**, not camera-visible network streaming / terrain quadtree with out-of-core fetch. The 3D viewport does not automatically drape every scientific result on the mesh |

## Semantics and reproducibility

- Existing 28 Terrain operation IDs remain available; new P1 algorithms are
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
- Volume uncertainties are conditional on **user-supplied** one-sigma
  vertical error, and must not be confused with surveyed confidence intervals.
- LOD index selection reduces GPU face count by a zoom-dependent factor but
  currently retains full vertex data in a GPU buffer.

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
by adding test names. The P0 gate's **synthetic 95+ score is not a P1
scientific certificate**. P1 currently records
\`reference_validation=not_performed\` in individual run receipts pending
independent reference validation.

## Automated tests

- \`tests/test_terrain_p1_science.py\`: analytic D-infinity, external inflow,
  corner NoData and invariants, fitted polynomial curvature and large windows,
  designed grade and uncertainty, DSM blockers, multi-observer optimization,
  weighted suitability GeoTIFF, LOD boundary continuity, and bounded breach.
- \`web/src/terrainP1.test.ts\`: algorithm-specific run identity and source
  provenance, no unrelated parameter contamination.
- \`web/src/terrainP1LOD.test.ts\`: camera mesh LOD node indices, boundary
  cells and NoData face exclusion.
- \`.github/workflows/terrain-science.yml\`: existing independent-GDAL P0
  reference gate plus an additional, mandatory P1 analytic/GeoTIFF test step.
- The repository's full Python, TypeScript, native, browser, memory and release
  suites remain mandatory prior to merging.

**Current release state:** work in progress. Branch
\`feature/terrain-p1-science-95\` and PR #9 are intentionally separate from
\`main\`; release readiness requires fresh green checks at the exact head SHA.
