# Network science

The module serves geospatial research, not commercial navigation. Its 22 methods
operate on explicit directed multigraphs. Import WGS84 GeoJSON FeatureCollections
of pre-noded LineStrings. Each feature can declare string `edge_id`, `source`,
`target`, `direction` (both/forward/reverse), and positive custom cost.
Without explicit endpoint IDs, exact endpoint coordinates identify junctions.
Intersections of lines are never automatically connected: bridge and tunnel
topology is not inferred from geometry. Inspect topology first. Geodesic length
is computed on WGS84; otherwise supply a uniform declared cost unit.

## Methods
- Topology, weak connectivity, directed shortest path, OD costs, nearest facility.
- Service reach includes partial reachable edge support under linear within-edge
  impedance; it does not invent a polygon.
- Gravity accessibility and two-step floating catchment area (2SFCA) use directed
  origin-to-facility costs; supply and demand must be supplied explicitly.
- Harmonic and weighted Brandes centrality, with exact floating-point cost ties.
- Geodesic circuity, single-edge disruption criticality, baseline/scenario OD
  comparison and independent Bernoulli stochastic failure reliability.
- Raster exposure samples uniform geodesic midpoints in native cells; applies
  raster scale/offset, records source SHA-256 and coverage. Hazard closures
  use maximum sampled value; unknown coverage is rejected below the declared
  threshold. Sampling is not an exact spatial integral or ground-validated risk.

Wilson intervals describe conditional Monte Carlo sampling uncertainty only.
Neither independent edge failure nor a simple hazard threshold establishes
real-world failure probability. Dynamic traffic, turn penalties and public transit schedules are not implemented. Local OSM snapshot construction and correlated hazard simulation are supported as described below.

## Workbench and evidence
Network Analysis has its own top-level control, project layer and imagery source
selectors, results layer toggle, CSV and GeoJSON exports, research receipt and
shared Scientific Figure Studio recipes (degree distributions, cumulative route
cost, reach and OD curves, centrality, exposure, criticality and reliability).
The API catalog publishes the input schema. All results are scoped to the current
project in the client. Limits: 10,000 edges, 100,000 vertices, 10,000 OD pairs,
2,000 nodes for exact centrality, 256 tested critical edges, 2,000 trials and
bounded search/sampling work.

## Acceptance
Run `python -m pytest -q tests/test_network_science.py` and the browser
network-science spec using the existing test infrastructure. Tests use hand
computed directed graph references, known parallel path multiplicities,
disconnection, partial geodesic length, supply conservation, seeded Monte
Carlo, native GeoTIFF calibration and actual scientific rendering. The new
branch is based on the unmerged remote-sensing development commit, not main;
the inherited CI has its own outstanding acceptance.

The map uses a separate network result source, numeric graduated symbols for exposure, accessibility, centrality and criticality, and explicit closure colors. Current Terrain, Spatial Analysis and Remote Sensing result rasters can be reused directly as exposure inputs, without exporting and re-uploading them. Display scaling is recorded separately from raw scientific values.

## Advanced network research
18 methods now include exact positive-cost bicriteria Pareto paths (bounded labels and comparisons; no silent approximation), raster-adjusted edge impedance and routing, and Gaussian copula spatially correlated edge failures. Marginal failure probabilities are explicit. Exponential covariance uses spherical chord distances between geodesic edge midpoints; Wilson intervals remain conditional simulation intervals. The OSM snapshot importer builds topology from shared node IDs, preserves direction and separates coincident distinct IDs, and requires explicit class-based scenario speeds. It does not fetch live OSM, enforce turn restrictions or predict real traffic. Its import receipt reports restriction relations and source hash. The workbench can reuse adjusted edges with the adjusted_cost attribute and exports the OSM source receipt. Tests cover non-dominance, directed reuse, marginal dependence limits and OSM grade separation.

## Facility location and supply competition
22 methods include enhanced distance-decayed 2SFCA, exact finite-candidate p-median and maximum coverage, and two-stage capacitated allocation using sparse HiGHS LP. P-median rejects candidate sets that cannot serve all demand; maximum coverage retains uncovered origins. Allocation first maximizes divisible served demand, then minimizes network cost at fixed maximum flow with a separately checked feasibility tolerance. It is not integer vehicle routing or household assignment. Tests independently check optimal finite candidate selection, uncovered demand, capacity conservation, transport cost and distance-decayed supply conservation.

The distance-decayed catchment calculation shifts costs by the nearest eligible origin for each facility; the common exponential factor cancels algebraically, preventing complete underflow and preserving modeled supply. The input network generated by the OSM importer and raster impedance product embeds reproducible source lineage. Advanced figure regressions exercise actual algorithm output through PNG and SVG rendering. This is code and test coverage, not a claim of passing full repository acceptance.
