# AI building footprint extraction

This workflow runs a real local building segmentation model, retains the source
pixel grid, creates geographic candidate polygons, and connects the outputs to
the existing editor, measurements and scientific figure studio.

## Local setup

Run from the repository root in the GeoFathom Python environment:

```powershell
python -m pip install -e ".[vision]"
python -m vision.provision
```

The explicit provisioning command installs the approximately 220 MB HOT
DINOv3-S/UperNet ONNX model. It pins the source revision, size and SHA-256 from
`vision/catalog/hotosm-dinov3s-buildings.json`. Model weights remain local data
and are not committed to Git. Repeating the command verifies the existing file;
different existing weight bytes are not overwritten. The browser never downloads
weights automatically.

The model uses RGB bands 1/2/3 in the 0–255 encoding, HOT mean/std normalization,
256-pixel inference tiles and 32-pixel context halos. Its three output channels
are mask logit, boundary logit and distance, not three competing classes. Only the
mask channel receives sigmoid decoding in this implementation. The existing
multi-class semantic interface remains available.

Use the existing `GEOFATHOM_VISION_MODELS_DIR` to select a model directory. CPU is
the default. The existing CUDA runtime supports
`GEOFATHOM_VISION_DEVICE=cuda`; install the appropriate ONNX Runtime GPU package
and CUDA dependencies for the host. This change was exercised with real CPU ONNX
inference; a GPU was not available for this round of acceptance. Binary head
decoding returns to the CPU even when model execution uses CUDA. Runtime usage
telemetry is disabled before session construction.

## Workbench

1. Open a project and select a georeferenced, high-resolution RGB GeoTIFF in
   **Raster / AI**.
2. Expand **GeoAI raster analysis & change detection** and choose
   **AI building footprint extraction**.
3. Select the installed building model. Set the building probability threshold
   and minimum footprint area. Optionally select a polygon on the map and enable
   **Use selected polygon as study area**.
4. Run the analysis using the existing operator administration token. The job
   reports progress and supports cancellation.
5. Preview the candidate outlines and save them to the project for boundary
   review and editing. Saving does not mark a candidate as verified.
6. Use **Open scientific figures** for the existing professional vector-map and
   numeric-table recipes, with the run's source/model metadata attached.

Downloads include `footprints.geojson`, `footprints.csv`, `mask.tif`,
`probability.tif`, and a footprint-area histogram in PNG/SVG. GeoJSON is WGS84;
rasters retain the source CRS, affine transform and native pixel size. CSV records
area, perimeter, mean building probability, compactness and source pixel count.
Each download is checked against its recorded SHA-256 and remains scoped to its
own project and completed task.

## Scientific behavior

- Context tiles retain each core exactly once. Polygonization runs after the
  complete mask is assembled, so processing seams do not split connected regions.
- AOI crops retain the original pixel grid and read model context from the
  original scene outside the AOI when available. Pixel centers determine AOI
  membership; exported raster-cell boundaries approximate the selected boundary
  to source-pixel precision.
- Source nodata and pixels outside the study area are 255 in the binary mask and
  -1 in the probability raster. Valid background is 0. Holes are preserved.
- Areas and perimeters use the existing WGS84 ellipsoidal measurement engine.
  Mean probabilities are model scores, not calibrated accuracy estimates.
- Connected foreground regions are candidate roof/footprint regions. Touching
  buildings may merge. This version does not claim instance segmentation or
  verified ground-level building footprints. No automatic rectangularization or
  hole filling is applied.
- Vector results are bounded to the largest 100 regions, with explicit truncation
  metadata. Area and minimum-pixel filters affect retained vector candidates;
  the mask and raw foreground-pixel count retain the thresholded prediction.
- Input bytes and model/manifest bytes are captured by the existing private
  execution snapshot mechanism. Raster/inference/CUDA slots, subprocess limits
  and cooperative cancellation are shared with the existing job system.

## Public-data acceptance

```powershell
python scripts/building_benchmark.py --output data/building-public-run --download-only
python scripts/building_benchmark.py --output data/building-public-run
```

For kernel-enforced offline evaluation on Linux with libseccomp installed, use
`--offline` on the second command. That process denies socket syscalls, including
native-library telemetry. Use a fresh run directory for each evaluation.

The benchmark selects three evenly spaced chip names from each of four HOT test
projects before inspecting labels. Archives are revision- and SHA-256-pinned.
The author's original image bytes and georeferencing sidecars are repackaged
losslessly as GeoTIFF; dataset-viewer JPEG previews are not used. Label 0/255 is
explicitly converted to 0/1. Every jointly valid pixel is evaluated; uncertain
predictions are not excluded to increase accuracy. A separate maximum-cardinality
one-to-one object IoU match scores the retained vector polygons. Empty-scene
precision/recall/F1 are reported as zero with raw counts, rather than averaged
as perfect building detection.

The first run is recorded in `building-extraction-public-benchmark.json`, with
its comparison figure in `building-extraction-public-comparison.png`:

| Sample | Result |
| --- | --- |
| Projects / countries / chips | 4 / 4 / 12 |
| Scored pixels | 786,432 |
| Building precision | 0.7115 |
| Building recall | 0.2647 |
| Building IoU | 0.2390 |
| Building F1 | 0.3858 |

These are integration-smoke measurements, not a model quality pass. The small
sample includes many empty chips. The upstream post-processing search included
HOT train/test chips, so this dataset cannot establish untouched external
generalization. Recall is insufficient for reliable automatic building
inventories. Independent labeled regions, model comparison and local adaptation
remain necessary before making a research accuracy claim.

The numerical test graph verifies ONNX transport, seams, holes, AOIs and nodata.
It is never counted as evidence of actual building recognition accuracy.

## Sources and attribution

- Model: <https://huggingface.co/hotosm/dinov3s-buildings>, revision
  `f7254545dfbbf10a40594d5a5fb62136902000ae`.
- Input/output and normalization reference:
  <https://github.com/hotosm/fAIr-models/blob/develop/models/dinov3s_buildings/README.md>
  and its `pipeline.py` preprocessing/postprocessing implementation.
- Dataset: <https://huggingface.co/datasets/hotosm/vhr-building-segmentation>,
  revision `8d3e64e5c69aa37209953cce3a48df1092bc7c94`.
- Imagery: contributors of Open Imagery Network / OpenAerialMap, CC-BY-4.0.
  Labels: OpenStreetMap contributors, ODbL-1.0. Dataset curation: HOT.
- The model card declares CC-BY-4.0 and notes a separate DINOv3 backbone license.
  The model and backbone licenses must be retained with redistributed weights.
