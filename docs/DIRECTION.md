# Product direction

GeoFathom should remain a general geospatial intelligence environment.

## Supported foundation

- MapLibre editable vertices, move, midpoint insertion/deletion, snapping and undo/redo
- Rectangle/circle, polygon holes and splitting, boolean overlay, numeric coordinates
- Persistent project layers with colors, visibility, locks, duplication and geometry revisions
- Additional C++ performance kernels for snapping, topology and path simplification

- Georeferenced GeoTIFF import, MapLibre image overlays and local imagery catalog
- C++ seeded-color mask tracing with deterministic Python fallback
- Optional SAM 2 promptable image segmentation with explicit installation
- Pixel-to-WGS84 polygon conversion and geodesic area measurement
- Public STAC imagery metadata search limited to a bounded region

- Persistent projects with SQLite and GeoJSON import/export
- Metric buffer, overlay, area comparison and geodesic distance API
- Groq GPT-OSS 120B as the default free-tier cloud model
- Auditable AI tool execution for bounded area searches
- Place/name search with multiple candidates
- Bounded OpenStreetMap polygon search with area filters and category selection
- Honest geometry availability
- Map centering and boundary display
- User-drawn polygon and line measurements
- GeoJSON export
- Gemini 3.8 Flash as the optional free-tier multimodal model
- Saluki retained only as an optional local inference adapter
- API connectivity probe and synthetic cross-provider intent benchmark
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
