# Providers and model integration

GeoFathom separates intelligence, map data, imagery and spatial mathematics.

## Local model through Ollama

Set these environment variables before launching the API:

    GEOFATHOM_LLM_PROVIDER=ollama
    GEOFATHOM_LLM_MODEL=<installed model tag>
    GEOFATHOM_OLLAMA_URL=http://localhost:11434

Saluki 27B is the preferred local default. Set the exact installed model
tag as shown by `ollama list`; the example `saluki` is not guaranteed to
exist on every machine. For a larger alternative, evaluate Qwen3.5-35B-A3B, rather than maintaining
an additional small-model configuration. The adapter does not assume any model
is installed and accepts any compatible server tag. No weights are included in this repository.
See [Models](MODELS.md) for GGUF and llama.cpp integration.

The intent model performs only bounded classification and place-name extraction. It can select locate or discover operations. The assistant reports that unbounded natural-language area discovery is not available. The separate /discover endpoint supports bounded, explicitly incomplete OpenStreetMap polygon searches.

## OpenAI-compatible local servers

    GEOFATHOM_LLM_PROVIDER=openai-compatible
    GEOFATHOM_LLM_MODEL=<served model name>
    GEOFATHOM_OPENAI_BASE_URL=http://localhost:8080/v1
    GEOFATHOM_OPENAI_API_KEY=

This adapter also supports local llama.cpp servers. These adapters can later be extended with hosted models. Do not put secrets in source control.

## Geospatial data

Search uses Nominatim through /search. Configure GEOFATHOM_CONTACT_EMAIL for a responsible HTTP application identity. Public Nominatim must not be used for bulk geocoding. Its policy includes a low request cap and attribution requirements.

A result can be:
- mapped: a polygon or line exists in the returned dataset, subject to validation.
- location_only: a placemark exists but no usable boundary was returned.

Bounded area discovery uses a capped public Overpass way query. Zoom into a small neighborhood, choose building, landuse or water, and filter by square meters. It does not cover every OSM relation or unmapped feature.

Displayed area measurements use mapped geometry, not the display bounding box. A bounding box is only used to zoom the map.

## Base maps and imagery

Default maps are OpenStreetMap street tiles, not satellite imagery. They require OSM attribution and adherence to the tile policy.

For authorized raster imagery, set:

    VITE_SATELLITE_TILES_URL=https://your-licensed-provider/{z}/{x}/{y}.jpg
    VITE_SATELLITE_ATTRIBUTION=Your imagery provider

The optional imagery toggle is enabled only when a provider URL is configured. Do not extract commercial map imagery in violation of its license. Visual segmentation is not implemented in this starter.

## API examples

Check capabilities:

    curl http://localhost:8000/capabilities

Search a place:

    curl "http://localhost:8000/search?q=Hongqiao%20Airport"

Measure a WGS84 polygon:

    curl -X POST http://localhost:8000/measure \
      -H "Content-Type: application/json" \
      -d '{"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}'

Ask the assistant:

    curl -X POST http://localhost:8000/assistant \
      -H "Content-Type: application/json" \
      -d '{"message":"Measure Hongqiao Airport area"}'

Native geometry endpoints are `/spatial/contains` and
`/spatial/bbox-overlap`. They use C++ when compiled kernels are available
and fall back to Python/Shapely otherwise.

An HTTP 501 response from /vision/segment explicitly means no imagery segmentation provider is installed.
