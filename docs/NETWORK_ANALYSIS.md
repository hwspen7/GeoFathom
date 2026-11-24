# Network science

The module serves geospatial research, not commercial navigation. Its 14 methods
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
real-world failure probability. No traffic dynamics, turn penalties, automatic
OSM network building, correlated hazard simulation or public transit schedules
are implemented in this version.

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
