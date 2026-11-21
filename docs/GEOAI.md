# GeoAI raster analysis

GeoFathom now has three bounded, georeferenced raster analysis workflows.
They are launched through the map's **GeoAI raster analysis & change detection**
panel and run as project-scoped, persistent background jobs. No complicated
natural-language prompt is required.

## Workflows and scope

| Operation | Method | Inputs | Results |
| --- | --- | --- | --- |
| Spectral vegetation/water candidates | NDVI (NIR–Red) or NDWI (Green–NIR) | One GeoTIFF; two *explicitly selected* bands; index threshold | Polygon estimates, ellipsoidal area, pixel counts |
| Two-date spectral changes | Reproject the second raster into the first raster's analysis grid, then compare normalized differences | Two different GeoTIFFs; shared band mapping; change threshold | Index-gain/index-loss polygons and source image IDs |
| Semantic segmentation | Tiled ONNX Runtime model with NCHW float32 input | Local operator-installed ONNX model + manifest, chosen image | Multi-class polygons, model ID, aggregate confidence, review flags |

These are intentionally separate. NDVI/NDWI and their change masks are
**deterministic remote-sensing calculations**, not semantic AI detections.
A vegetation-index gain does **not** prove a new tree, construction or
a change in ownership. The ONNX pipeline performs actual machine-learned
inference when compatible weights are installed.

C++17 native kernels compute normalized-difference pixels and change labels
using contiguous float32 arrays and uint8 validity masks, with a matching
NumPy fallback. GDAL/Rasterio remains responsible for reprojection, sensor
band reads and nodata; GEOS/GDAL handles vector polygonization. Returned
metadata discloses which native or fallback engine actually ran.

All outputs use WGS84 GeoJSON, measured areas from the geographic geometry
engine, explicit image source IDs, estimated boundary status, and a
`requires_user_review` flag. Results are **preview only** until explicitly
saved to the current project as editable, versioned features. The operation
never silently changes existing GIS features.

## Operator-provisioned ONNX models

Install the optional runtime (CPU by default):

```bash
python -m pip install -e ".[dev,vision]"
```

Configure an operator-owned directory, for example:

```dotenv
GEOFATHOM_VISION_MODELS_DIR=/srv/geofathom/vision-models
GEOFATHOM_VISION_DEVICE=cpu
```

For CUDA, use `GEOFATHOM_VISION_DEVICE=cuda` and install a matching
`onnxruntime-gpu` runtime instead of the standard CPU package.

A model is discovered only when the directory contains matching
`landcover.onnx` and `landcover.json` files. Manifest example:

```json
{
  "description": "Local land cover model trained for this sensor",
  "classes": ["background", "building", "road", "vegetation", "water"],
  "bands": [1, 2, 3],
  "tile_size": 256,
  "input_scale": 255,
  "mean": [0, 0, 0],
  "std": [1, 1, 1]
}
```

- Classes must be indexed from zero, with class zero as background.
- Band numbers are **1-based** GeoTIFF bands. Configure them for the
  actual training sensor, not assumed Sentinel/Landsat display order.
- Tiles must be 128, 256 or 512 square pixels. Input tensor must be
  `[1,3,tile_size,tile_size]` float32 NCHW, with normalization
  `(raw / input_scale - mean) / std`.
- First output must contain either float logits
  `[1,num_classes,tile_size,tile_size]` or integer class IDs
  `[1,tile_size,tile_size]`; all outputs must match the model manifest.
- The default fast preview is bounded to 768 pixels along its longest
  dimension and a maximum of 36 model tiles. Full-resolution mode streams
  bounded tiles over the source raster; the first implementation caps work
  at 64 million source pixels, not arbitrary scenes. In both modes at most
  100 polygon features are returned.
- Model file paths come only from the server's configured model directory.
  The browser can select only a validated model ID; it cannot upload an
  arbitrary executable model or ask the server to fetch a remote model URL.
- Compatible ONNX weights are not included in the repository. The server
  does not falsely advertise AI detections before a real model is configured.
  `GET /vision/models/segmentation` shows available models and runtime.

## Spectral change constraints

A change comparison uses two georeferenced source rasters. Rasterio
`WarpedVRT` aligns the later image to the reference raster grid. Only
pixels valid in **both** images contribute to changed regions. A
non-overlapping footprint fails explicitly; missing date metadata is not
invented. Both images must use the selected band indices for the same
physical spectral channels; source CRS and pixel grids may differ.

This first implementation does not solve atmospheric correction, cloud
removal, BRDF/illumination normalization or multitemporal registration errors
beyond coordinate-based reprojection. Comparisons need similarly calibrated
radiometry, scene quality review and adequate spatial resolution.

## API, execution, testing

- `GET /vision/models/segmentation` — discovered local model manifest IDs.
- `POST /projects/{id}/jobs` — operation kinds:
  `spectral_index`, `spectral_change`, `semantic_segmentation`.
- `GET /projects/{id}/jobs/{job_id}` — queue/result state, failure reason,
  source IDs and polygon candidates.

All three operations require the local administrator token on job submission,
to prevent untrusted users from scheduling expensive imagery inference.
The standard two-thread local worker queue applies: job results persist
up to 5 MB. In full-resolution mode, each tile updates task progress and
checks cancellation. GDAL polygonization checks periodically, but a single
native/model call remains noninterruptible until it returns. A local
synchronized ONNX session pool bounds cached sessions and simultaneous
inference. Neither the queue nor the pool is a distributed GPU scheduler.

The regression suite in `tests/test_geoai.py` covers known synthetic
spectral masks, geodesic polygon outputs, temporal gain/loss, invalid band
mapping, nonoverlapping rasters, project access isolation, model manifest
validation and a mocked semantic ONNX inference contract. The browser test
in `web/e2e/geoai.spec.ts` covers the actual GUI workflow selection.
A real model deployment still needs acceptance tests using licensed,
annotated satellite imagery and hardware-specific latency/VRAM metrics.

## Remaining GeoAI development

The common vision workflow provides a base for real deployment of
sensor-specific models and related tools. It does **not** yet offer
general-purpose object detection, cloud/shadow masking, pansharpening,
multispectral data-cube construction, 3D surface reconstruction,
training/fine-tuning, fully automated quality repair, or distributed
raster tiling. These should be integrated as verified providers and
bounded operations rather than fabricated results.

## Full-resolution streaming controls

Select **Full-resolution streamed analysis** in the GeoAI panel. Spectral
index and change jobs use the selected window size; semantic ONNX analysis
uses the fixed model-manifest input tile shape. The API accepts
`full_resolution: true`, `max_pixels` (maximum 64,000,000) and
`memory_mb` (4–512). Spectral index/change also accept `tile_size`
(64, 128, 256 or 512). The default maximum is 16,777,216 pixels.

Full-resolution spectral and semantic workflows write a temporary compressed
mask to local disk. Polygonization occurs across the full mask, preserving
connected regions crossing processing-window seams. Predictions from
tile-based models can still show edge effects, since model-context halos
and blending are not yet implemented. Output remains an estimate requiring
human review and optional manual boundary correction.

ONNX runtime behavior is configured by:

```dotenv
GEOFATHOM_VISION_MAX_CACHED_MODELS=2
GEOFATHOM_VISION_PARALLEL_INFERENCE=2
GEOFATHOM_VISION_TENSOR_MEMORY_MB=128
GEOFATHOM_VISION_CPU_THREADS=2
# CUDA defaults to one concurrent inference and an advisory GPU arena.
# GEOFATHOM_VISION_DEVICE=cuda
# GEOFATHOM_VISION_GPU_ARENA_MB=2048
```

These are per-process controls. In particular, the CUDA arena setting is
not a hard VRAM allocation guarantee. Model logits and predicted labels are
validated for shape, class range and non-finite values. Softmax values from
unvalidated models are not assumed to be calibrated probabilities.
