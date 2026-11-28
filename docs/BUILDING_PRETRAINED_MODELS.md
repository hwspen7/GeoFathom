# Pretrained building candidates

Status: local research adapters; no upstream checkpoint has been executed by CI. Existing HOT/WHU baseline remains unchanged. No remote code or weights are vendored. Obtain each checkpoint from its official README and review upstream code and checkpoint rights before use. UniBuild's pinned source has no declared license; do not distribute or use without applicable permission. SAMPolyBuild code is Apache-2.0; Pix2Poly code is MIT; checkpoint terms must be checked separately. Never enable unsafe pickle deserialization if a checkpoint is rejected.

## Pinned sources

| Candidate | Official repository | Revision |
|---|---|---|
| UniBuild | https://github.com/zhu-xlab/UniBuild | cfbbdf5682cb435000a19fe7f3f66c3cc341ccc6 |
| SAMPolyBuild | https://github.com/wchh-2000/SAMPolyBuild | 0edf90e3deb5170c141f396db0c77fa5c3295860 |
| Pix2Poly | https://github.com/yeshwanth95/Pix2Poly | 4e4c00359b41f31fe80f7fbdab0fa50eb7a46ab8 |

Each upstream runs in a separate operator-local process. Keep checkout clean and checkpoint outside it. Use the appropriate dependency environment; do not install SAM/Pix2Poly's legacy dependencies into the qualified GeoFathom CUDA environment. The external adapter requires GeoFathom's base dependencies (rasterio, scipy, shapely, pydantic, etc.). UniBuild uses its full HR-DPT checkpoint with strict state-dict load; no gated backbone download. It applies FP32 tile inference at 512/384, native overlap blending, one tile per batch, exact normalization and no upsampling. SAM uses its automatic WHU-mix runner (score .3), the published model's resize and result coordinates, no annotations. Its old Lightning/MMCV dependency compatibility and tensor-only checkpoint loading require real verification. Pix2Poly uses INRIA configuration, 224/168 native windows, no pretrained encoder download, greedy ring generation, and nearest-tile-center ownership; tile truncation and finite vertex capacity are limitations. Its older Transformers/TIMM stack requires isolation. All three require complete uint8 RGB chips <=2048 pixels per axis. No native large-AOI production integration yet.

## Validation-only procedure

`python scripts/building_external_predict.py --model unibuild --upstream LOCAL_REPO --checkpoint LOCAL_CHECKPOINT --dataset OLD/dataset.json --output NEW_SMOKE --device cuda --authorized --limit 1`

Only pass --authorized after verifying code and weight permissions. Smoke run must be finite, native aligned, and contain hash-bound artifacts. Run again without --limit into a fresh directory to generate all validation predictions. Replace --model and paths for SAMPolyBuild/Pix2Poly in their separate environments. Each produces a signed-by-hash (not cryptographic authentication) receipt, checkpoint SHA-256, source SHA-256, settings, duration, and peak PyTorch allocated memory; no test predictions are generated.

`python scripts/building_external_study.py --dataset OLD/dataset.json --baseline hotosm-dinov3s-buildings-fp32 whu-unetplusplus-efficientnet-b4 --bundles UNIBUILD_FULL SAM_FULL PIX_FULL --output NEW_COMPARISON --device cuda`

One bundle is sufficient. Full coverage, exact identity, native grid and valid support are mandatory. The prior flip/50:50/.35/adaptive/6 baseline remains fixed. The grid compares UniBuild alone/with baseline, native vector models, whole-instance semantic support, and greedy object consensus if both vector models are present. Raster collisions are resolved deterministically by confidence and source order; original rings retained, invalid rings and overlaps reported. For Pix2Poly the published score is constant 1, not calibrated confidence. No fabricated hole topology. Binary mask support is not a probability; calibration results are suppressed for vector aggregate reporting. Matching is a heuristic, not globally optimal. Selected native raster/feature bundles preserve the original CRS or pixel coordinates. They are not RFC7946 WGS84 GeoJSON.

This is only validation ranking. INRIA and WHU may overlap pretraining. Do not open the frozen test split or automatically promote candidates. Independent external regions and permission review, actual checkpoint load, GPU accuracy/parity, large-AOI tiling, production worker/API/UI integration are separate release gates.

## Optional UniBuild production conversion candidate

After authorized native inference, use `python scripts/building_unibuild_export.py --upstream LOCAL_REPO --checkpoint LOCAL_CHECKPOINT --sample VALIDATION_IMAGE --output NEW_EXPORT --authorized`. It exports one fixed 512×512 binary-probability head, checks the self-contained graph and CPU parity on up to two real native crops. It does not install the model. After review, copy model.onnx/model.json to the configured local model directory under a new matching identifier (never overwrite). Re-run building_gpu_acceptance.py and the full-image validation grid. The upstream overlap blend and GeoFathom halo-core tiler differ; CPU tile parity alone cannot establish deployment accuracy. Actual upstream export success is untested until real weights are available.

## Pix2Poly checkpoint transfer and encoder caching

Use --pix-variant inria, spacenet or whu (WHU requires 144 vertices instead of 192); default remains INRIA-compatible. --encoder-cache is opt-in: one encoder call per tile, same upstream autoregressive decoder and permutation assignment. Compare identical original and optimized runs using `python scripts/building_pix2poly_parity.py --dataset DATASET --original ORIGINAL --optimized CACHED`. Require byte-identical polygon payloads and exact instance partitions; this is chip-local numerical parity, not a universal speed guarantee.

`python scripts/building_transfer_study.py --dataset DATASET --baseline hotosm-dinov3s-buildings-fp32 whu-unetplusplus-efficientnet-b4 --bundles inria=INRIA_FULL spacenet=SPACENET_FULL whu=WHU_FULL --output NEW_TRANSFER --device cuda`

Multiple checkpoints of the same model can now be ranked in one run, with per-region metrics and explicit noninferiority rejection reasons. Native candidates remain included, and additive experiments preserve every primary pixel; only nonoverlapping whole secondary instances with enough semantic support may be added. No hard semantic filtering of the primary. Cross-checkpoint transfer on INRIA remains validation-only; use separately sourced imagery with documented provenance before deployment.

SAMPolyBuild automatic prediction now configures one CUDA device, batch size 1, zero loader workers, non-distributed execution and no ROI multiprocessing or training checkpoint callbacks. This avoids several Windows worker/legacy distributed hazards without changing the model weights. It still requires a compatible compiled MMCV distribution; the configuration is regression-tested but real upstream execution is not yet qualified.
