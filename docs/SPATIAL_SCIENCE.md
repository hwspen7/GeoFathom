# Spatial Analysis: scientific computing contract

Spatial Analysis is independent of the Terrain module. Its catalog exposes 52 executable methods across vector, raster, sampling, spatial statistics, decision and integrated operations. The same validated endpoint is used by the manual workbench and the future AI research orchestrator. No language model is required for numerical computation.

## Inputs and outputs

- Open Analysis → Spatial science → Open Spatial Analysis. Load WGS84 GeoJSON or the current drawn geometry and/or georeferenced GeoTIFFs. For vector-only methods select a projected metre EPSG appropriate to the study area. Raster integration uses the raster's metre CRS. No automatic CRS guess or silent raster alignment.
- The raster path uses calibrated selected bands, scale and offset, exact grid alignment, NoData masks and explicit physical units. All methods are bounded by feature, pixel, payload and arithmetic-work limits.
- Outputs are real GeoJSON, GeoTIFF, CSV and a JSON calculation receipt. The vector result can be displayed independently on the map; raster/table outputs open in the existing Scientific Figure Studio. Export preserves actual numerical values, not merely a screenshot.
- GET /analysis/science/catalog provides typed algorithm parameters, required input types, assumptions, output types and a JSON Schema for future AI tool registration. POST /analysis/science/run performs the selected method. AI planning, autonomous orchestration and automated literature research are separate future work.

## Scope

The 52 methods include exact fractional overlap zonal statistics/class area, Gaussian point intensity, spatially balanced and stratified sampling with design weights, permutation Moran/Geary/join-count diagnostics, AHP consistency-ratio enforcement, TOPSIS, weighted overlay and exact two-criterion Pareto cells. The module intentionally excludes full geostatistical inference, SAR, routing, time-series modeling and LiDAR, which belong to dedicated research modules. Geometry measurement is planar within the selected metre CRS; it is not a geodetic field-survey certification.

## Acceptance

tests/test_spatial_science.py contains parameterized analytic checks across the entire catalog, including independent window statistics, projected metric geometry, sample design conservation, spatial graph formulas, classification coverage and invalid input rejection. Passing these fixtures supports implementation correctness for the tested conditions, not arbitrary real-world accuracy or a subjective 90-point rating. Real large/heterogeneous datasets, independent cross-engine comparisons and UI workflows must also be verified before claiming scientific production maturity.

The workbench provides a bounded synchronous request. Cancelling the browser request discards the response; it does not guarantee server-side interruption. Persistent background execution and multi-step automated chaining remain future work.

Managed rasters, complete saved project layers and Terrain output GeoTIFFs can be selected directly. Raster alignment is an explicit operation (nearest or continuous bilinear); classification uses ordered numerical breaks. Derived rasters can be reused as inputs. Zonal coverage ignores fractional slivers smaller than 1e-8 of a cell area, to suppress inverse-projection round-trip artifacts.

Local Moran and Getis–Ord Gi* expose statistics, permutation p, BY-adjusted q and significant class rasters. Significance is conditional on random-label exchangeability, neighborhood definition and multiplicity correction, not proof of a physical causal process. Raster results have a separate bounded, Mercator-aligned PNG map preview; scientific GeoTIFFs retain their original full-resolution grid.

The automated acceptance gate requires a passing analytic test for each of the 52 methods, contract/error tests, GDAL CLI cross-interface grid alignment, and a 512×512 conservation/mask/sampling stress fixture. A missing, skipped or failed required case prevents the gate from passing. This is a 90-point numerical acceptance floor for the declared fixtures, not a claim of external scientific certification or broad production maturity. Browser and cross-platform checks must independently pass.
