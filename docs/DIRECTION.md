# Product direction

GeoFathom should remain a general geospatial intelligence environment.

## Supported foundation

- Persistent projects with SQLite and GeoJSON import/export
- Metric buffer, overlay, area comparison and geodesic distance API
- Saluki default model with optional larger reasoning profile
- Auditable AI tool execution for bounded area searches
- Place/name search with multiple candidates
- Bounded OpenStreetMap polygon search with area filters and category selection
- Honest geometry availability
- Map centering and boundary display
- User-drawn polygon and line measurements
- GeoJSON export
- Saluki 27B as the preferred swappable local intent model
- Native C++ topology with a Python fallback for geographic queries
- Explicit capability discovery and basic API tests

## Next engineering goals

- Provider registry with search fallback, per-provider policy and provenance
- Collaborative project access, feature versioning and robust undo/redo
- Geospatial feature index (PostGIS or equivalent) for area/radius/shape queries
- Vector feature import from GeoJSON, Shapefile and GeoPackage
- Georeferenced raster upload with tiled rendering
- Promptable visual segmentation via a replaceable CV provider
- Geometry quality checks and optional manual validation
- Multi-object batch analysis and spatial comparison
- Temporal change detection using dated imagery
- Digital elevation models and terrain operators
- Reproducible, attributed reports and dataset exports
- Authentication and distributed quota enforcement for production

A primary acceptance rule: every result must reveal whether it came from a verified dataset, mapped geometry, image-derived estimate, or a user-created outline. Never invent precision or declare an unavailable model operation successful.
