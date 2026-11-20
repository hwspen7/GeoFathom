# GeoFathom

**GeoFathom** is an extensible, local-first geospatial intelligence workspace. Search for places, examine authoritative or openly mapped geometries, draw and measure boundaries, and let an optional local language model coordinate searches. The platform is designed to grow into imagery segmentation, spatial discovery, terrain analysis, and change detection without binding its core to a single AI provider.

## Runtime choices

Default AI model: **Groq-hosted GPT-OSS 120B** on a rate-limited free API tier.
Optional second model: **Gemini 3.8 Flash** with a separate free API allowance.
No large cloud model weights run on your local GPU; the local RTX 4070 Ti SUPER
can focus on geospatial/CV processing. Both providers require user-owned API
keys. Saluki 27B remains an optional local alternative via Ollama.
See [model setup](docs/MODELS.md).

GeoFathom uses **Python for orchestration, GIS analysis and provider adapters**
and **C++17 for optional performance-sensitive geometric topology**. The
native module has a correctness-preserving Shapely/Python fallback.

## What works

- Search geographic places through OpenStreetMap Nominatim, with source attribution and honest boundary availability.
- Discover mapped buildings, land-use polygons, and water areas by geodesic area inside a bounded map viewport (OpenStreetMap Overpass).
- Display map results and candidate locations on an interactive map.
- Calculate geodesic area, perimeter, and length from GeoJSON using PyProj and Shapely.
- Draw, edit by restarting a drawing, measure, and export polygons as GeoJSON.
- Execute geographically grounded natural-language tasks using GPT-OSS 120B, Gemini 3.8 Flash, or a configured local model, with explicit tool traces and viewport constraints.
- Persist projects and GeoJSON features in local SQLite storage and reload them between sessions.
- Run metric buffers, polygon overlays, area comparisons and WGS84 distance analyses through FastAPI.
- Run without an LLM: direct place search, bounded spatial discovery, and polygon measurement remain available.
- Optional C++ native topology engine for point containment and bounding box overlap with Python fallbacks.
- Discover service capabilities and health via explicit API endpoints.

**Not yet implemented:** automated satellite-image segmentation, verified land ownership or zoning, unbounded global parcel discovery, and guaranteed precision for missing boundaries. The AI runtime currently executes named-place lookup and bounded area search, not arbitrary multi-tool autonomous planning. A vision-provider contract exposes this limitation rather than fabricating results.

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

## Configure free cloud model APIs

Copy `.env.example` to `.env` at repository root and set your own keys:

```ini
GEOFATHOM_LLM_PROVIDER=groq
GEOFATHOM_LLM_MODEL=openai/gpt-oss-120b
GEOFATHOM_GROQ_API_KEY=your-groq-api-key

GEOFATHOM_ANALYSIS_PROVIDER=gemini
GEOFATHOM_ANALYSIS_MODEL=gemini-3.8-flash
GEOFATHOM_GEMINI_API_KEY=your-gemini-api-key
```

Create keys using [GroqCloud](https://console.groq.com/keys) and
[Google AI Studio](https://aistudio.google.com/api-keys).
No billing upgrade is required to attempt requests within each provider's
available free-tier limits. Limits, model availability and data policies may
change; review them in your own dashboard.

Never commit `.env`, put keys in the web frontend, or send secrets in support
messages. When keys are absent, GeoFathom still provides non-AI GIS tools.
`GET /models` reports configuration and `POST /models/probe` makes a small
real API call to confirm access without contacting the geocoder.
The web UI has a **Test API** control for this probe.

For local inference instead, configure `GEOFATHOM_LLM_PROVIDER=ollama`
and use the exact model tag installed on your machine. See [Models](docs/MODELS.md).

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
