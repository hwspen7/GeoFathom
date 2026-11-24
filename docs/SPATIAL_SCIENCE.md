# Spatial Analysis: scientific computing contract

Spatial Analysis is independent of the Terrain module. Its catalog exposes 67 executable methods across vector, raster, sampling, spatial statistics, decision and integrated operations. The same validated endpoint is used by the manual workbench and the future AI research orchestrator. No language model is required for numerical computation.

## Inputs and outputs

- Open Spatial Analysis → Open Spatial Analysis. Load WGS84 GeoJSON or the current drawn geometry and/or georeferenced GeoTIFFs. For vector-only methods select a projected metre EPSG appropriate to the study area. Raster integration uses the raster's metre CRS. No automatic CRS guess or silent raster alignment.
- The raster path uses calibrated selected bands, scale and offset, exact grid alignment, NoData masks and explicit physical units. All methods are bounded by feature, pixel, payload and arithmetic-work limits.
- Outputs are real GeoJSON, GeoTIFF, CSV and a JSON calculation receipt. The vector result can be displayed independently on the map; raster/table outputs open in the existing Scientific Figure Studio. Export preserves actual numerical values, not merely a screenshot.
- GET /analysis/science/catalog provides typed algorithm parameters, required input types, assumptions, output types and a JSON Schema for future AI tool registration. POST /analysis/science/run performs the selected method. AI planning, autonomous orchestration and automated literature research are separate future work.

## Scope

The 67 methods include exact fractional overlap zonal statistics/class area, Gaussian point intensity, spatially balanced and stratified sampling with design weights, permutation Moran/Geary/join-count diagnostics, AHP consistency-ratio enforcement, TOPSIS, weighted overlay and exact two-criterion Pareto cells. The module intentionally excludes full geostatistical inference, maximum-likelihood SAR/SEM, routing, time-series modeling and LiDAR, which belong to dedicated research modules. Geometry measurement is planar within the selected metre CRS; it is not a geodetic field-survey certification.

## Acceptance

tests/test_spatial_science.py contains parameterized analytic checks across the entire catalog, including independent window statistics, projected metric geometry, sample design conservation, spatial graph formulas, classification coverage and invalid input rejection. Passing these fixtures supports implementation correctness for the tested conditions, not arbitrary real-world accuracy or a subjective 90-point rating. Real large/heterogeneous datasets, independent cross-engine comparisons and UI workflows must also be verified before claiming scientific production maturity.

The workbench provides a bounded synchronous request. Cancelling the browser request discards the response; it does not guarantee server-side interruption. Persistent background execution and multi-step automated chaining remain future work.

Managed rasters, complete saved project layers and Terrain output GeoTIFFs can be selected directly. Raster alignment is an explicit operation (nearest or continuous bilinear); classification uses ordered numerical breaks. Derived rasters can be reused as inputs. Zonal coverage ignores fractional slivers smaller than 1e-8 of a cell area, to suppress inverse-projection round-trip artifacts.

Local Moran and Getis–Ord Gi* expose statistics, permutation p, BY-adjusted q and significant class rasters. Significance is conditional on random-label exchangeability, neighborhood definition and multiplicity correction, not proof of a physical causal process. Raster results have a separate bounded, Mercator-aligned PNG map preview; scientific GeoTIFFs retain their original full-resolution grid.

The automated acceptance gate requires a passing analytic test for each of the 67 methods, contract/error tests, GDAL CLI cross-interface grid alignment, and a 512×512 conservation/mask/sampling stress fixture. A missing, skipped or failed required case prevents the gate from passing. The updated evidence gate has a 95-point minimum numerical acceptance floor for the declared fixtures, not a claim of external scientific certification or broad production maturity. Browser and cross-platform checks must independently pass.

Advanced methods include exact anisotropic-cell-spacing Euclidean proximity, focal quantile, directional lag diagnostics, bivariate Moran permutation inference, Dirichlet weight uncertainty, spatially buffered out-of-fold raster regression, descriptive covariance ellipses and exact area-weighted quantiles. Zonal intersection uses bounded vectorized GEOS operations. The decision uncertainty is conditional on explicit weight assumptions, and regression scores are held-out spatial diagnostics, not causal evidence.

Spatial Research Figures bind actual null draws, directional lag statistics, sampling weights, held-out prediction, zonal coverage and criterion weights to the common Scientific Figure Studio. Five specialized recipes add to the shared catalog (40 basic, 173 professional). Global Moran/Geary/join count support rook or queen weights. Dirichlet decision uncertainty uses exact mean and variance; threshold probabilities retain Monte Carlo frequencies and a separate plug-in MC standard error. These additions do not establish empirical maturity without passing acceptance.

Additional mandatory acceptance covers shared-edge metric precision, exact small-sample randomization references, anisotropic distance against brute force, missing-data zonal conservation, sampling-design repeated estimates, extreme weights, analytic uncertainty and real result-to-figure pipelines. Scores refer to the defined evidence gate, not universal algorithm accuracy.

All derived rasters now include full-valid-grid quantile diagnostics (or class frequencies for up to 50 classes), explicitly excluding NoData. The result-specific figure shortcuts use these exact summaries rather than values sampled from the display preview. Calculation receipts include SHA-256 of the returned CSV and canonical GeoJSON, in addition to the original raster hashes. Global randomization budgets account for both population shuffles and graph edges, including isolated cells.

## Advanced spatial modeling and scale sensitivity

Seven additional methods extend the shared catalog: distance-band and KNN global Moran randomization, descriptive multiscale Moran/dispersion with coverage, exact empirical isotropic variograms, correlated linear-difference uncertainty, rook spatial lag structural regression via 2SLS, and fixed-bandwidth Gaussian geographically weighted leave-one-out prediction. The latter two expose residual Moran diagnostics and distinguish structural fits from held-out predictions; neither establishes causal effects or external-site validation. Spatial weights use explicit metric distances, stable KNN ties, bounded directed edges and row standardization. Spatial lag reports instrument rank and first-stage diagnostics; scientific interpretation requires independently justified instruments. Difference uncertainty uses four aligned same-unit rasters and an explicitly supplied same-cell error correlation. Square-window min/max/range now use separable exact reductions, lowering radius-dependent work without changing NoData semantics. Full geostatistical covariance fitting, kriging, SEM, arbitrary user matrices and out-of-core processing remain outside this bounded implementation.
