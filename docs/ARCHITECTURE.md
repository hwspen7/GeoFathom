# Architecture

GeoFathom is a geospatial platform rather than a model-specific demo or an airport-area calculator.

## System boundaries

- **Workspace:** React + TypeScript + MapLibre GL; direct place lookup, an optional natural-language input, candidate selection, polygon/line drawing, geodesic result display, and GeoJSON export.
- **API:** FastAPI; validates geographic requests and returns machine-readable results and capabilities.
- **Discovery:** Geocoding uses OSM Nominatim, and constrained polygon discovery uses OSM Overpass. The next data-source abstraction can add Overture, regional gazetteers, feature indexes and local PostGIS without modifying map views.
- **Geospatial computation:** Shapely validates geometry, PyProj/PROJ performs WGS84 ellipsoidal measurement. The AI model never supplies calculated area values.
- **AI intent:** A local Ollama model or an OpenAI-compatible server may normalize an instruction into a structured intent. The no-model fallback is deterministic. No model is a source of boundary truth.
- **Vision:** Explicit provider protocol, not yet implemented. Segmentation must use licensed imagery, georeferencing and accuracy metadata. Missing capability is reported with HTTP 501.
- **Data contract:** GeoJSON in EPSG:4326 coordinates (longitude, latitude), a provenance string, a boundary-status indicator, and measurement metadata.

## Data flow

1. User enters a location or an instruction.
2. The client calls /search or /assistant.
3. The service normalizes the request and searches the configured geocoder.
4. The result carries candidate coordinates and, if available, mapped geometry.
5. Geometry is validated and measured by /measure, and the map renders the actual polygon, line or point.
6. The user can draw a different shape and measure it independently.
7. Export preserves geometry and a basic source label.

Place candidates are not guaranteed matches. A name lookup is not evidence of a property boundary, airport perimeter, ownership or zoning. If a result provides only a point, the frontend shows a point and asks the user to draw a boundary.

## Extension points

**Search providers:** implement a shared candidate result with id, name, lon/lat, bbox, geometry and source. Use an explicit confidence/evidence field when integrating new sources.

**AI providers:** implement the IntentProvider protocol. A replacement model returns structured, bounded actions and delegates facts to tools. Avoid API- or model-specific logic elsewhere.

**Vision providers:** implement VisionProvider and return georeferenced geometry, imagery acquisition date, license, confidence, CRS and quality flags. Never treat a pixel polygon as geographic geometry without image georeferencing.

**Feature discovery:** integrate a spatial index and query plan that supports attribute filters, bounding boxes, proximity, class labels and area ranges. The current /discover endpoint supports a narrow bbox and a capped subset of OSM way polygons for buildings, land use and water. It is not exhaustive, ignores multipolygon relations and must not be interpreted as a complete parcel inventory. A global unnamed-area query requires a spatial index; do not attempt a worldwide raster scan per user query.

**Analysis:** introduce versioned internal operation schemas only where necessary for compatibility, not public marketing release labels. Possible operators include buffer, intersect, union, coverage, comparisons, temporal overlays, terrain and visibility.

## Measurement limitations

- Longitude/latitude inputs are assumed to be WGS84 and validated for range.
- Geodesic area is ground-projected polygon area on the WGS84 reference ellipsoid, not surface area over relief.
- Large polygons spanning more than a hemisphere and antimeridian-crossing shapes need special handling.
- Polygon rings must be topologically valid. Invalid or self-intersecting input is rejected, not silently repaired.
- The Nominatim public search service has shared capacity limits. This starter enforces a best-effort per-process throttle and caches requests, but multiple workers or public traffic need a coordinated limiter or owned provider.
- The application must not infer land legality, property ownership, or engineering suitability from imagery alone.

## Security and deployment

The example is intended for local development. Do not expose the unprotected API directly on the public internet. Add authentication, request quotas, telemetry, environment-specific CORS, persistent caching, safe model endpoints and centralized request rate limiting before production deployment.
