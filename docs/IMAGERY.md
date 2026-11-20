# GeoFathom georeferenced imagery and tracing

This workflow follows the same GIS separation of raster data, georeferencing,
vectorization, measurement and editing found in professional tools such as
QGIS and GDAL. It supports real georeferenced imagery **without assuming that
every color region is an actual building or airport boundary**.

## First working end-to-end workflow

1. Start FastAPI and the web workspace.
2. Set a strong `GEOFATHOM_MODEL_ADMIN_TOKEN` in the server's root `.env`.
3. Obtain a **licensed georeferenced GeoTIFF** with an embedded CRS and
   affine coordinate transform, or generate a reproducible demonstration:

       python examples/create_demo.py

4. Open **Georeferenced imagery** in the web sidebar, enter the administration
   token and upload the GeoTIFF. Maximum upload: 64 MB.
5. The raster appears in its original geographic position. If testing the
   generated sample, zoom to the automatically loaded layer near (0, 0).
6. Choose **C++ color region**, a tolerance (start at 20), and a 512 px window.
   Click **Start automatic outline**, then click a homogeneous region.
7. The C++/Python region algorithm creates a binary pixel mask. Rasterio/GDAL
   polygonizes it with its actual geographic affine transform. The service
   converts the polygon to WGS84 and PyProj measures its geodesic area.
8. The result appears on the map with explicit image-derived provenance and
   a warning if the target extends beyond the analysis window. You can
   redraw a corrected shape with the existing map tools.
9. Use **Projects & saved geometry** to save or export the outline as GeoJSON.

**The demo raster is synthetic and is not presented as real satellite imagery.**

## Model-based tracing (optional)

The alternate SAM 2 provider uses Meta's official promptable
`SAM2ImagePredictor` with `facebook/sam2.1-hiera-small` by default.
On a CUDA-equipped local workstation, install a compatible PyTorch version
and the [official SAM 2 package](https://github.com/facebookresearch/sam2).
Then configure:

    GEOFATHOM_SAM2_ENABLED=1
    GEOFATHOM_SAM2_MODEL_ID=facebook/sam2.1-hiera-small

SAM 2 can download model weights the first time it is used. This only occurs
after explicit opt-in, not at startup or during the deterministic color
workflow. Choose **SAM 2** in the imagery panel to use a click prompt.
The segmentation is an estimate and must be checked on the map. The service
returns HTTP 501 when the optional model is not enabled or installed.

## Public STAC metadata discovery

The **Find public satellite scenes** control searches a bounded map
viewport against the Element 84 Earth Search STAC API, using the public
`sentinel-2-l2a` collection. It returns scene identifiers, acquisition dates,
cloud cover and source links. It does **not** automatically download imagery
or assert permission for reuse. Many Sentinel-2 bands have coarse spatial
resolution for individual-building tracing. Users must inspect the actual
asset, its band composition, resolution and license before importing it.

Professional references:
- https://documentation.qgis.org/3.44/en/docs/user_manual/processing_algs/gdal/rasterconversion.html
- https://rasterio.readthedocs.io/en/stable/topics/features.html
- https://docs.ogc.org/cs/25-005/25-005.html
- https://maplibre.org/maplibre-style-spec/sources/

## Architecture and performance

- `imagery/` (Python, Rasterio/GDAL): GeoTIFF upload validation,
  metadata, geographic transforms, windowed reads, previews, STAC search.
- `vision/` (Python): optional SAM 2 inference, segmentation orchestration,
  mask-to-GeoJSON polygonization, quality and provenance metadata.
- `geometry/native/` (C++17): bounded 4-connected seeded RGB segmentation
  and existing geometric kernels, compiled with CMake.
- `geometry/mask.py` (Python): typed `ctypes` bridge with a deterministic
  Python fallback for machines without the compiled native library.
- `geometry/measure.py` (Python, PyProj): reference-ellipsoid
  area and perimeter measurements from WGS84 GeoJSON.
- `web/`: MapLibre native georeferenced image source + overlay drawing,
  geospatial click prompts, saved project geometries.

The trace operation reads only a bounded 32–1024 px original-pixel window.
This limits CPU and GPU inference memory and prevents loading arbitrarily
large image rasters into GPU memory. Concurrent trace work is serialized
in one FastAPI process. Distributed task queues and model worker
isolation are future additions for multi-user deployment.

## Important limitations

- RGB similarity is a deterministic connected-region heuristic, not semantic
  segmentation. It cannot identify an airport fence or building boundary
  merely by understanding a text description.
- A pixel-derived outline is not a surveyed, cadastral or legally valid
  boundary. Small rasters or coarse-resolution imagery have finite accuracy.
- The map image overlay uses four georeferenced corners and is not an
  orthorectification engine. Serious off-nadir/terrain distortion needs a
  correctly orthorectified raster before upload.
- The data library is local-first and has no per-user isolation or production
  access controls. File uploads require the existing admin token, but previews
  and metadata are accessible to anyone with network access to the service.
  Do not publicly expose the development server without authentication.
- Complex nodata imagery, cloud cover, antimeridian-crossing rasters, very
  large rasters and cross-tile object merging need additional engineering.
- No cloud-hosted LLM is needed to perform deterministic raster tracing.
