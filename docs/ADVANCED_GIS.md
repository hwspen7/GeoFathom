# Advanced GIS editing, terrain and visual correction

GeoFathom's GIS workspace supports topologically linked editing, network
tracing, attribute tables, GDAL/OGR file interchange, and local terrain
analytics. Python owns coordinate systems, GDAL/OGR integration and
transactional projects. C++ owns spatial acceleration and DEM gradients.
Browser editing stays interactive without a remote call per mousemove.

## Professional workflows

### Shared boundary / linked vertex editing

1. Save two polygon features in a project with coincident boundary vertices.
2. Open one saved polygon. Enable **Vertices** and **Linked/shared vertices**.
3. Drag a common vertex. The sidebar previews the affected project features,
   their revision numbers, and whether a locked or invalid feature blocks the
   edit.
4. Confirm the operation. All involved geometries update in one SQLite
   transaction, or none do. Changes create new immutable feature revisions.
5. If either layer is locked, a revision changed, or geometry becomes invalid,
   the operation is rejected.

The implementation links **existing near-coincident vertices** (up to a
configurable 2 m tolerance; browser defaults to 0.05 m). It does not yet infer
or split unmatched interior segment nodes. Use topology preview before every
linked edit; do not assume the same accuracy as professional cadastral data.

API endpoints:

- \`POST /projects/{project_id}/topology/preview\`
- \`POST /projects/{project_id}/topology/move\`

### Trace existing vectors between two points

Save a line network (roads, stream centerlines or other vector paths). Choose
**Trace network**, then click start and end locations within 30 m of the
network. The Python GIS module nodes segment crossings and runs a shortest
connected path search; the C++ BVH locates candidate edges quickly.

- \`POST /edit/trace\`
- Up to 300 line paths and 20,000 input positions
- Trace returns a WGS84 LineString with measured geodesic length

If features cross but represent grade-separated infrastructure, preprocess
their connectivity; geometric intersection alone does not prove access.

### Attributes, filters and bulk edits

Open **Professional GIS tools → Attribute table**. Search by name, source
or attribute name with substring, equals, numeric lower/upper bounds or
existence tests. Select rows, assign a typed text, number or boolean value,
and save a batch of updates.

- API query scans up to 10,000 features, pages a maximum of 200 rows
- The current web table shows the first 100 matched rows; use narrower
  predicates for large collections
- Changes are transactional, revision-aware and reject locked layers
- Existing project layer display is initially limited to 200 features;
  spatial indexed database paging is an identified future scale-up

### GIS vector interchange

Open **GIS file import / export** in the same section.

| Format | Import | Export |
| --- | --- | --- |
| GeoJSON | Yes | Yes |
| GeoPackage (.gpkg) | Yes | Yes |
| KML | Yes | Yes; current KML export covers single Points, Lines and Polygons |
| GPX | Yes; reads waypoints, routes and tracks | Yes; points and lines only |
| Shapefile ZIP | Yes; validated flat ZIP | Yes; output ZIP |

Imported geometries require a declared CRS. Coordinates are transformed to
WGS84 by PyProj, then geometry validity and size are checked. Upload size
is limited to 25 MB; ZIP expanded size to 80 MB; import batch to 100
features. Unsafe ZIP member paths are rejected. Cadastral datasets with
multiple thousands of features require a separate paginated import workflow.

### Projected DEM surface analysis

Import a GeoTIFF whose first band is a DEM with **elevations in meters** and
whose *horizontal CRS is projected in meters*. A regular north-up grid is
required.

Select a polygon → **Terrain slope & elevation profile → Analyze** to
receive minimum, maximum and mean elevation, relief, mean and maximum slope,
circular mean downhill aspect and valid-pixel count.

Select a LineString and click Analyze to obtain a sampled elevation profile.
C++ Horn 3×3 gradients compute slope and aspect; Numpy provides a reference
fallback. Analysis is bounded to 1024×1024 pixels per area selection and
does not interpret RGB satellite imagery as an elevation model.

- \`POST /terrain/analyze\`
- \`POST /terrain/profile\`
- No automatic DEM downloads or vertical datum conversion
- Model assumes verified elevations in meters, not feet

### AI-assisted correction

Install the optional SAM 2.1 CUDA model using the setup in
[IMAGERY.md](IMAGERY.md). Upload a georeferenced raster, then choose
**Include (+)** clicks, **Exclude (−)** clicks and two **Box** corners.
Click **Refine mask**. GeoFathom converts WGS84 prompts into original
image-window pixels, performs local segmentation, vectorizes the mask
and records model and prompt provenance in the output.

- \`POST /vision/refine\`
- Up to 20 positive and 20 negative clicks, plus a rectangle
- Explicit HTTP 501 when the optional local model is unavailable
- Model weights must be separately installed; cloud LLMs cannot replace
  georeferenced image segmentation
- All generated outlines require human review

## Native performance and validation

C++ source files: \`geometry/native/spatial.cpp\` and
\`geometry/native/terrain.cpp\`.

The spatial accelerator builds a balanced bounding-volume hierarchy for up
to 1,000,000 metric segments and answers repeated nearest-segment queries.
Python wraps this with \`geometry/spatial.py\` and validates coordinate
units. A viewport-local spatial hash handles browser dragging without
resending every pointer position to the backend.

CI exercises a 100,000-segment native index and a corresponding browser
index, checks a known synthetic 10% DEM incline, verifies GIS round-trips,
runs native Release/Debug builds, and performs headless Chromium drawing,
dragging and project interactions with Playwright. Windows MSVC testing
is also configured.

To run locally:

    python -m pip install -e ".[dev]"
    cmake -S . -B build/native
    cmake --build build/native --config Release
    python -m pytest -q

For browser tests:

    cd web
    npm install
    npx playwright install chromium
    npm run test:e2e

Playwright launches development FastAPI and Vite servers and uses a temporary
project database. It does not exercise the optional GPU SAM installation or
validate legal survey accuracy. CI results should always be checked for the
latest commit rather than an older green run.

## Remaining constraints

- Topological editing matches co-located vertices, not fuzzy polygon edges.
- CPU/GPU high-resolution processing is not yet distributed across worker nodes.
- Geometries crossing ±180° longitude need a specialized geographic workflow.
- The current local SQLite server is not a multiuser secured GIS deployment.
- Indexed SQLite/PostGIS pagination is implemented; distributed vector-tile streaming and million-feature rendering benchmarks are not.
- DEM values and CRS/vertical units must be verified by the user.
- Imported vector data and raster imagery are not proof of land ownership.
