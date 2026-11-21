# Professional GIS P0 / P1 / P2 workflows

This extension builds on GeoFathom's existing Python FastAPI, C++ native
geometry kernels, MapLibre editing canvas, persistent SQLite projects, and
geodesic WGS84 measurements. It deliberately avoids an artificial second
backend, nested version folders or a complete desktop GIS rewrite.

## P0 — everyday survey mapping and quality control

### Spatial selection

Open **GIS selection, QA & print layout → Select by location**. Drag a
rectangle on the map or choose a pre-drawn polygon as a lasso; select
\`intersects\`, \`within\`, \`contains\`, \`touches\` or \`crosses\`, then click
**Select matches**. Saved objects matching the exact Shapely predicate are
highlighted. Hidden layers are excluded by default; this is configurable.

The backend first filters candidates using an on-disk SQLite R-tree, then
applies exact geometrical relationships. The spatial index is automatically
updated when geometry is created, moved, restored or deleted. Legacy projects
get a lazy backfill. API:

- \`POST /projects/{id}/spatial/select\`
- \`GET /projects/{id}/features/viewport?west=...&south=...&east=...&north=...&limit=250&offset=0\`

The SQLite candidate limit is 25,000 features per query. A viewport request
with too many candidates is rejected instead of exhausting memory. MapLibre
renders up to the user-requested page; the original unpaged workspace
currently loads its first 200 saved objects.

### Topology quality assurance

Open **Topology quality inspection → Analyze topology**. Detect:

- Polygon area overlaps, with WGS84 geodesic measured area.
- Exactly duplicated mapped polygons.
- Interior holes in merged polygon coverage.
- Uncovered areas inside a user-selected polygon study area.
- Potential dangling endpoints of line networks.

Issue geometries are overlaid in red, with a report. Changes are **not**
automatically repaired; review each issue first. Externally missing coverage
is not guessed without a study area. A dangling endpoint might be an
intentional dead end. No cadastral or regulatory accuracy is implied.

API: \`POST /projects/{id}/quality/topology\`.

### Vector PDF print layouts

Open **PDF print layout**, enter map title and choose A4/A3/US Letter,
portrait or landscape, current viewport or all visible features, latitude /
longitude grid and legend. Click **Export vector PDF**.

The ReportLab renderer emits true vector paths, heading, projection-aware
metric scale bar, graphic north arrow, timestamp, layer legend, metadata and
geographic caveats. It uses regional azimuthal equidistant projection
for map drawing, then recovers WGS84 content. It does not blindly copy
public raster tiles into a PDF. Feature outlines are not land-ownership
proof. Current max extent is 70° longitude; antimeridian print regions
require a specialized pipeline.

API: \`POST /projects/{id}/print/pdf\`, media type \`application/pdf\`.

## P1 — advanced cartography and coordinate systems

### Graduated numeric colors

Open **Advanced cartography & EPSG → Graduated numeric choropleth**, choose
layer, numeric attribute, classification, and number of classes:

- *Equal interval* — evenly spaced numeric thresholds.
- *Quantile* — approximate equal counts per class.
- *Fisher–Jenks natural breaks* — minimizes within-class squared deviation
  using dynamic programming.

Resulting class breaks and colors are stored in the existing versioned layer
style and map legend. Input is limited to 10,000 project features per layer;
Jenks uses at most 500 evenly sampled sorted numeric values to bound cost.
The model does not assume categorical values are numeric.

Endpoints:
- \`POST /analysis/classify\`
- \`POST /projects/{id}/symbology/graduated\`

### Advanced label rules

Layer styling additionally provides font priority, offset in ems, optional
label prefix/suffix, automatic or along-line placement, and callout
connectors for displaced point features. Every setting is validated,
persisted with a style revision, and rendered as plain MapLibre label
expressions. Original label text is never evaluated as HTML/JavaScript.

Note: this is not full QGIS PAL or ArcGIS Maplex. Full per-feature label
drag handles, collision priorities spanning providers and nested
expressions require a dedicated cartographic layout engine.

### EPSG coordinate systems

Open **Project EPSG coordinates & grid**, enter a registered \`EPSG:code\`,
toggle a projected coordinate grid or transform the selected point /
viewport-center coordinates using PyProj. The project CRS, grid visibility
and revision are stored in SQLite. Examples:

- \`EPSG:4326\`: stored WGS84 geographic coordinates
- \`EPSG:3857\`: Pseudo-Mercator projected meters
- \`EPSG:32617\`: WGS84 / UTM zone 17N
- \`EPSG:26917\`: NAD83 / UTM zone 17N

Import/export already handles declared external source CRS through
GDAL/OGR. Changing the project EPSG **does not** change stored WGS84
GeoJSON or the WebMercator MapLibre basemap; it affects grid and coordinate
conversion. Support for a complete alternative-projection map canvas is a
separate larger feature.

Endpoints: \`GET/PUT /projects/{id}/crs\`,
\`POST /projects/{id}/crs/transform\`,
\`GET /projects/{id}/crs/grid\`.

## P2 — geospatial services and scalable storage

### OGC WMS / WMTS / WFS / OGC API Features

Configure the server environment:

\`\`\`dotenv
# Only HTTPS hosts controlled or trusted by the operator are eligible.
GEOFATHOM_OGC_ALLOW_HOSTS=maps.example.org,geo.example.org
GEOFATHOM_MODEL_ADMIN_TOKEN=<your-own-long-random-token>
\`\`\`

Then open **OGC map & feature services**, enter a standard HTTPS endpoint,
service type, layer/collection identifier, attribution and administrator
token. WMS/WMTS source layers can be toggled in MapLibre (raster
GetMap/GetTile proxy). WFS and OGC API Features are fetched over a bounded
WGS84 viewport and previewed on the map before explicit import into the
SQLite project.

- Service records are project scoped. Registration/removal requires the
  administrator token. Tokens are never persisted in SQLite.
- Request URL is stored as a validated HTTPS base URL; arbitrary client
  URLs are not forwarded to the proxy.
- Configure trusted hostnames rather than arbitrary domains. HTTP redirects,
  embedded URL credentials, query fragments and private literal IPs are
  rejected. Public DNS and TLS management remain deployment concerns.
- HTTP request timeout is 15 seconds; vector response max 5 MB, tile max
  2 MB. At most 100 geometries can be fetched in a single vector request.
- A vector response must be valid GeoJSON with recognized geometries.
  Invalid provider responses are rejected; sources are not silently
  imported into projects.

API:
- \`GET/POST /projects/{id}/ogc\`
- \`DELETE /projects/{id}/ogc/{source_id}\`
- \`GET /projects/{id}/ogc/{source_id}/capabilities\`
- \`GET /projects/{id}/ogc/{source_id}/features\`
- \`GET /projects/{id}/ogc/{source_id}/tiles/{z}/{x}/{y}\`

WMS output uses EPSG:3857 GetMap requests; WMTS uses a configured tile
matrix set; a service using incompatible CRS/matrix IDs requires provider-
specific configuration. Registration alone does not verify the external
service is online—use **Capabilities** and then a real tile/vector request.

### Optional PostgreSQL / PostGIS

SQLite R-tree pages work without external infrastructure. For larger
datasets, enable a PostGIS 16+ server, PostGIS extension and Python package:

\`\`\`bash
python -m pip install -e ".[dev,postgis]"
\`\`\`
\`\`\`dotenv
GEOFATHOM_POSTGIS_DSN=postgresql://geofathom:<password>@localhost:5432/geofathom
\`\`\`

Admin-authenticated \`POST /projects/{id}/postgis/sync\` takes a stable
project-scoped SQLite snapshot (up to 100,000 features), writes to a PostGIS
geometry(Geometry,4326) table and builds a GiST index in a PostgreSQL
transaction. \`GET /projects/{id}/postgis/features\` serves indexed bbox
pages. The mirror may be stale until the next sync. A failed PostgreSQL
transaction is rolled back rather than returning partial rows.

Endpoints:
- \`GET /postgis/status\`
- \`POST /projects/{id}/postgis/sync\`
- \`GET /projects/{id}/postgis/features?west=...&south=...&east=...&north=...\`
- \`DELETE /projects/{id}/postgis\` (admin)

SQLite remains authoritative; this is a **read-oriented PostGIS mirror**,
not yet a concurrent multi-user editing database. Locking, history, audit,
concurrent write access control and deployments should be addressed before
using the external store as the authoritative editor.

### Local persistent task queue

**Persistent background GIS jobs** supports:
\`topology_qa\`, \`spatial_select\`, \`export_geojson\`,
\`postgis_sync\`, \`rebuild_index\`.

Jobs are stored in SQLite with queued, running, completed, failed,
cancelled and interrupted states. At most 32 pending/running tasks and
two worker threads per app process are used. Cancel requests prevent a
queued job from starting or discard the result of a running operation, but
cannot forcibly stop a Python/GDAL call already executing. Interrupted
tasks are not reported as completed.

Endpoints:
- \`POST /projects/{id}/jobs\` (202 Accepted)
- \`GET /projects/{id}/jobs\`
- \`GET /projects/{id}/jobs/{job_id}\`
- \`POST /projects/{id}/jobs/{job_id}/cancel\`
- \`GET /projects/{id}/jobs/{job_id}/download\` for completed GeoJSON exports.

PostGIS sync and index rebuild are administrator-only. Job results have
a 5 MB output cap. This local queue is not Redis/Celery or a remote
multi-node GPU cluster and it does not imply SAM2 is installed.

## Validation

- Python/SQLite spatial select, exact relations, topology issues, R-tree
  update/delete/backfill and bounded query tests
- PDF six page modes with extracted real text and service guardrails
- Quantile/equal-interval/Jenks, EPSG conversions and style security
- OGC API WMS/WMTS/WFS/Features request/response and allowlist tests
- Persistent job success, failure, cancellation, output and administrator
  tests
- PostGIS CI service container exercising real geometry sync and GiST
- Chromium tests for map rectangle dragging, PDF download, QA, graduated
  colors, project EPSG and queued job lifecycle
- Windows MSVC native build and Python GIS test suite

See [test matrix](TEST_MATRIX.md). Each claim should be checked against
the **latest** GitHub Actions run for the exact current commit.

## Remaining production needs

- Very large projects: vector tiling, async PostGIS incremental sync,
  multi-user conflict policies and richer indexing.
- OGC: service-specific tiled CRS/matrix compatibility, authentication,
  feature pagination, credentials vault, WMS styles and real-world provider
  conformance testing.
- Print layout: editable multi-page designer, full complex labels, legally
  licensed satellite basemap export, color management and accessible PDFs.
- GIS precision: dateline, poles, vertical datums, localized projection
  distortions and officially surveyed parcel boundaries.
- GPU: real model weights and CUDA installation; remote SAM2 inference and
  segmentation outputs are not validated by these CPU-focused tests.
