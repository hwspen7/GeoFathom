# Spatial Analysis: scientific computing contract

Spatial Analysis is independent of the Terrain module. Its catalog exposes 48 executable methods across vector, raster, sampling, spatial statistics, decision and integrated operations. The same validated endpoint is used by the manual workbench and the future AI research orchestrator. No language model is required for numerical computation.

## Inputs and outputs

- Open Analysis → Spatial science → Open Spatial Analysis. Load WGS84 GeoJSON or the current drawn geometry and/or georeferenced GeoTIFFs. For vector-only methods select a projected metre EPSG appropriate to the study area. Raster integration uses the raster's metre CRS. No automatic CRS guess or silent raster alignment.
- The raster path uses calibrated selected bands, scale and offset, exact grid alignment, NoData masks and explicit physical units. All methods are bounded by feature, pixel, payload and arithmetic-work limits.
- Outputs are real GeoJSON, GeoTIFF, CSV and a JSON calculation receipt. The vector result can be displayed independently on the map; raster/table outputs open in the existing Scientific Figure Studio. Export preserves actual numerical values, not merely a screenshot.
- GET /analysis/science/catalog provides typed algorithm parameters, required input types, assumptions, output types and a JSON Schema for future AI tool registration. POST /analysis/science/run performs the selected method. AI planning, autonomous orchestration and automated literature research are separate future work.

## Scope

The 48 methods include exact fractional overlap zonal statistics/class area, Gaussian point intensity, spatially balanced and stratified sampling with design weights, permutation Moran/Geary/join-count diagnostics, AHP consistency-ratio enforcement, TOPSIS, weighted overlay and exact two-criterion Pareto cells. The module intentionally excludes full geostatistical inference, SAR, routing, time-series modeling and LiDAR, which belong to dedicated research modules. Geometry measurement is planar within the selected metre CRS; it is not a geodetic field-survey certification.

## Acceptance

tests/test_spatial_science.py contains parameterized analytic checks across the entire catalog, including independent window statistics, projected metric geometry, sample design conservation, spatial graph formulas, classification coverage and invalid input rejection. Passing these fixtures supports implementation correctness for the tested conditions, not arbitrary real-world accuracy or a subjective 90-point rating. Real large/heterogeneous datasets, independent cross-engine comparisons and UI workflows must also be verified before claiming scientific production maturity.

The workbench provides a bounded synchronous request. Cancelling the browser request discards the response; it does not guarantee server-side interruption. Persistent background execution and multi-step automated chaining remain future work.
