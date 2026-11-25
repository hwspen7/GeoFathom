# GeoFathom

**GeoFathom** is an extensible, local-first geospatial intelligence workspace. Search for places, examine authoritative or openly mapped geometries, draw and measure boundaries, and let an optional local language model coordinate searches. The platform is designed to grow into imagery segmentation, spatial discovery, terrain analysis, and change detection without binding its core to a single AI provider.

## Runtime choices

Three **editable example presets** are provided: local Saluki 27B (selected by
default), Groq GPT-OSS 120B and Gemini 3.8 Flash. They are not a model
whitelist or fixed deployment plan. Users can add, modify and select any
compatible Ollama or OpenAI-compatible local/cloud model in the web UI,
using a server-side model catalog. See [model configuration](docs/MODEL_CONFIGURATION.md).

GeoFathom uses **Python for orchestration, GIS analysis and provider adapters**
and **C++17 for optional performance-sensitive geometric topology**. The
native module has a correctness-preserving Shapely/Python fallback.



## Direct GeoAI image analysis

The **GeoAI raster analysis & change detection** panel provides explicit,
form-driven NDVI/NDWI analysis, two-date spectral change detection (aligned
by Rasterio) and replaceable ONNX Runtime semantic segmentation. A bounded
full-resolution mode streams raster windows through native C++ spectral
operators and an optional local ONNX model without materializing all source
pixels in a NumPy array. All operations
run as bounded persistent background jobs; polygon candidates are previewed
before users explicitly save editable, provenance-tagged GeoJSON features.
ONNX model weights are not bundled and must be installed separately. Spectral
thresholding is deterministic, not AI classification.

See [GeoAI analysis setup, data contracts and limits](docs/GEOAI.md).

## Professional GIS workflows

The workspace now includes professional map PDF layouts, spatial rectangle
and polygon selection, topological polygon-gap/overlap QA, Jenks/quantile
graduated colors, advanced conditional labels, draggable label placement and callouts, project EPSG metadata/grid,
OGC WMS/WMTS/WFS/Features connectors, an indexed SQLite R-tree, an optional
PostGIS GiST mirror and a persistent local background task queue.

See [Professional GIS workflows](docs/PROFESSIONAL_GIS.md) and
[Automated validation](docs/TEST_MATRIX.md). External OGC and PostGIS
services need independently configured endpoints and cannot be assumed
operational on an unconfigured development machine.

## Cartographic labeling and map annotations

Per-layer labels can show names, sources, geodesic area/length or custom
attributes. Edit font size, halo, collision and zoom range, or add a
standalone point note. Categorized symbology colors features by unique
attribute values, with a matching legend. A scale bar, cursor coordinates
and identify inspector support day-to-day cartography. See
[Cartography guide](docs/CARTOGRAPHY.md) and
[Multi-dimensional test matrix](docs/TEST_MATRIX.md).

## Advanced professional GIS tools

The workspace additionally includes linked topological boundary previews and
atomic shared-node edits, tracing between two existing vector-network clicks,
filterable and bulk-editable attribute tables, KML/GPX/Shapefile ZIP/GeoPackage
interchange, local DEM slope/aspect and elevation profiles, and optional local
SAM 2 positive/negative/box mask refinement. Native C++ BVH acceleration
supports large nearest-edge queries, with a viewport spatial index in the
browser. See [Advanced GIS workflows](docs/ADVANCED_GIS.md).

CI includes Linux C++/Python/Web checks, Chromium Playwright UI tests,
Windows MSVC validation and standalone native address/undefined-behavior
sanitizers. Spectral pixels and change classes now use C++17 kernels when
available, with deterministic NumPy fallback. The native metric BVH
supports batched point queries to reduce Python/C++ ABI overhead.
See [native engine contracts and verification](docs/NATIVE_ENGINE.md). Optional local CUDA segmentation still requires
your own GPU and model installation.

## Interactive precision surveying and editing

The map now supports editable vertices, segment midpoint insertion, polygon
movement, snapping, live approximate measurements, authoritative WGS84
area/perimeter/distance, rectangles, geodesic circles, holes, polygon splits,
boolean overlays, precise coordinate construction, multi-layer projects and
versioned edits. The computational kernels are shared by Python + C++.
See [Survey editor](docs/EDITOR.md) for controls, tested capabilities and
limits.

## Georeferenced imagery and automatic outlines

GeoFathom can now import a locally provided GeoTIFF, display the correctly
located raster in MapLibre, and trace a clicked image region into a WGS84
GeoJSON polygon with an actual geodesic area. The default seeded-color method
runs in C++ when available and falls back to Python. Optional SAM 2 click
segmentation is supported after separate model installation.

Public satellite scene *metadata* can be searched using a bounded STAC
catalog query; actual imagery must still be obtained and imported with
appropriate usage rights. This avoids silently downloading arbitrary huge
or restricted raster assets.

To try the workflow without outside datasets, run:

```bash
python examples/create_demo.py
```

Then upload `data/synthetic_trace_demo.tif` from the web workspace.
See [Imagery and tracing](docs/IMAGERY.md) for setup and limitations.

## What works

- Search geographic places through OpenStreetMap Nominatim, with source attribution and honest boundary availability.
- Discover mapped buildings, land-use polygons, and water areas by geodesic area inside a bounded map viewport (OpenStreetMap Overpass).
- Display map results and candidate locations on an interactive map.
- Calculate geodesic area, perimeter, and length from GeoJSON using PyProj and Shapely.
- Draw, edit by restarting a drawing, measure, and export polygons as GeoJSON.
- Configure, add, edit and select local or cloud models through the workspace's model manager, without changing application code.
- Execute geographically grounded natural-language tasks using the selected model, with explicit tool traces and viewport constraints.
- Persist projects and GeoJSON features in local SQLite storage and reload them between sessions.
- Run metric buffers, polygon overlays, area comparisons and WGS84 distance analyses through FastAPI.
- Run without an LLM: direct place search, bounded spatial discovery, and polygon measurement remain available.
- Optional C++ native topology engine for point containment and bounding box overlap with Python fallbacks.
- Discover service capabilities and health via explicit API endpoints.

**Not yet implemented:** guaranteed semantic object recognition, verified land ownership or zoning, unbounded global parcel discovery, and precision guarantees for image-derived boundaries. Optional SAM 2 is supported but must be installed and configured separately. The AI runtime currently executes named-place lookup and bounded area search, not arbitrary multi-tool autonomous planning. A vision-provider contract exposes this limitation rather than fabricating results.

## Quick start

Requires Python 3.11+, Node.js 20+, and an internet connection for public map/geocoding data.

```bash
python -m venv .venv
# Activate the virtual environment, then:
pip install -e ".[dev]"
uvicorn core.main:app --reload
```

In another terminal:

```bash
cd web
npm install
npm run dev
```

Open http://localhost:5173. API docs are available at http://localhost:8000/docs.

## Configure models (local or cloud)

Copy `.env.example` to `.env` at repository root. Model configuration editing
requires a local administrator token, which is never committed to Git:

```ini
GEOFATHOM_MODEL_ADMIN_TOKEN=choose-a-long-random-token
GEOFATHOM_GROQ_API_KEY=
GEOFATHOM_GEMINI_API_KEY=
# Example for any additional API provider:
GEOFATHOM_MODEL_KEY_MY_PROVIDER=
```

In the web workspace, open **Ask GeoFathom → Manage models**. Enter the
administrator token, then add/edit local or cloud models, choose a model,
test the connection, and set a new default. Model names, tags and endpoints
persist to `data/model-catalog.json` by default. Model secrets are not stored
in this file, transmitted from the browser, or committed to Git.

Add remote API keys to the named variables in the server's `.env` and restart
FastAPI. For local Ollama models, no API key is required. Both built-in cloud
presets are optional and subject to their provider's free-tier constraints.
See [Model configuration](docs/MODEL_CONFIGURATION.md) and
[Models](docs/MODELS.md) for examples.

The web UI's **Test API** uses `POST /models/probe`, which performs a real
small model call. Plain GIS operations work even when no model is online.

### Windows PowerShell

From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn core.main:app --reload
```

Start the interface in a second PowerShell terminal:

```powershell
cd web
npm install
npm run dev
```

## Compile the C++ geometry engine (optional)

From the repository root:

```powershell
cmake -S . -B build/native
cmake --build build/native --config Release
ctest --test-dir build/native --build-config Release --output-on-failure
```

Python automatically uses the compiled library when available, otherwise it
uses Shapely/Python. Geodesic area continues to use PyProj regardless of native
availability.

## Project layout

```text
core/             Service assembly and configuration
geometry/         Python geodesics, topology and C++ native kernels
imagery/          GeoTIFF ingest, georeferencing, preview and public STAC search
vision/           Segmentation, mask vectorization and optional local SAM 2
places/           Geographic search and feature discovery
intelligence/     Interchangeable AI providers and intent processing
analysis/         Spatial buffer, overlay and comparison operations
storage/          Persistent SQLite projects and GeoJSON features
tests/            Automated service, storage and geospatial tests
web/              MapLibre and React interface
docs/             Architecture, integration contracts, usage notes
.github/workflows/ Python, C++ and web checks
```

## Principles

1. **Geometry is evidence.** The LLM never invents areas or geographic coordinates.
2. **Provenance is mandatory.** Results distinguish mapped boundaries from search points and estimated outlines.
3. **Models are interchangeable.** LLM and future vision engines use provider boundaries.
4. **Local-first costs.** Use existing hardware and public geospatial data where their licenses and rate limits permit.
5. **Extensibility first.** Avoid architecture that only understands airports or polygon area.

Public Nominatim and OpenStreetMap tile servers have usage policies. Configure a valid application identity and deploy dedicated or commercial providers for public/high-traffic use. Imagery analysis requires suitable imagery licenses.

See [Architecture](docs/ARCHITECTURE.md) and [Providers](docs/PROVIDERS.md) for details.

## Correctness and performance acceptance

Raster masks use 4-neighbor connectivity to avoid silently dropping
corner-touching invalid polygons. Full-size raster execution includes
temporary-disk availability, fragmentation and cancellation checks.
Task polling uses metadata-only responses with result JSON stored separately
in SQLite; features retain source and model SHA-256 provenance.

Synthetic 4K and 8K GeoTIFF processing is covered by Linux CI. The native
BVH supports concurrent reader leases, bounded traversal stacks and direct
NumPy double buffers. Optional million-segment, CUDA model and hardware
throughput acceptance are documented in
[the native engine guide](docs/NATIVE_ENGINE.md).

## Local COG / large GeoTIFF import

A server operator can import existing tiled GeoTIFF/COG files up to 8 GiB
without using the 64 MB browser upload endpoint:

```bash
python -m imagery.cli /path/to/large-scene.tif --name "Satellite source"
```

The CLI validates georeferencing and format, checks destination disk
capacity, copies the file into the managed imagery catalog and computes a
SHA-256 source checksum. It accepts **only a local filesystem path** and is
not exposed as an arbitrary remote URL import endpoint. Image metadata
displays source block shape, overview levels and tiled layout.

## Resilient local processing and secured deployments

GeoFathom runs in local mode by default: only loopback clients (and the
FastAPI test client) can reach the API. To deploy behind TLS on a trusted
reverse proxy, explicitly configure a high-entropy shared API credential:

```dotenv
GEOFATHOM_AUTH_MODE=required
GEOFATHOM_API_TOKEN=replace-with-a-random-string-of-at-least-32-characters
```

The browser's **Server access** panel holds that key in session storage.
This single-operator gate is *not* project-level RBAC or a complete
multi-tenant identity system. Do not expose an unauthenticated API.

Queued jobs use cross-process SQLite claims, unique worker leases, heartbeats
and shared raster/inference slots. For independent background workers on
the same machine, set `GEOFATHOM_EXTERNAL_WORKER=1` on the API and run
`python -m jobs.worker --workers 2` separately. Do not share SQLite on
NFS or across separate hosts. Raster/ONNX background jobs run in a killable
subprocess by default with configurable CPU RSS and wall-clock budgets.

```bash
python -m storage.maintenance --verify --audit-imagery
python -m storage.maintenance --repair-index --backup data/backup.sqlite
python -m jobs.worker --cleanup-days 30
```

For cloud-native Sentinel-2 COGs, the **Remote STAC/COG NDVI** GeoAI operation
resolves a validated Earth Search item and performs allowlisted GDAL range
reads on the NIR, red and SCL assets. It does not accept arbitrary remote
URLs or claim a full satellite scene was downloaded.
See [GeoAI data and model validation](docs/GEOAI.md).

For native-resolution AI building candidates, editable geographic footprints,
probability/mask GeoTIFFs and scientific figures, see
[Building extraction setup and measured public-data results](docs/BUILDING_EXTRACTION.md).

## Compute runtime qualification

See [compute architecture and acceptance](docs/COMPUTE_ACCEPTANCE.md) for
native scratch leases, optional CUDA, bounded model batching, persistent
pyramids, version archiving, distributed workers, RBAC, and hardware tests.

### Research result analysis

Terrain now supports named scenarios, common-cell algorithm differences, one-at-a-time sensitivity, seeded DEM uncertainty propagation and portable PDF/GeoTIFF/CSV experiment packages. See [Research analysis](docs/research-analysis.md) for methods, operation coverage, limits and reproduction.
