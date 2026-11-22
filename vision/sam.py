"""Optional promptable SAM 2.1 image segmentation.

The user must deliberately enable SAM and install its dependencies.
No model is downloaded during normal API startup or the color trace path.
"""

import os
from functools import lru_cache
from threading import RLock

import numpy as np

# SAM's cached predictor stores mutable image embeddings between calls.
# Serialize initialization and set_image/predict as one operation.
_predict_lock = RLock()


class VisionUnavailable(RuntimeError):
    """The optional image segmentation runtime is not configured."""


def sam_enabled() -> bool:
    return os.getenv("GEOFATHOM_SAM2_ENABLED", "0") == "1"


@lru_cache(maxsize=1)
def _predictor():
    if not sam_enabled():
        raise VisionUnavailable("SAM 2 is disabled. Set GEOFATHOM_SAM2_ENABLED=1 after installing SAM 2.")
    try:
        import torch
        from sam2.sam2_image_predictor import SAM2ImagePredictor
    except ImportError as error:
        raise VisionUnavailable("Install PyTorch and the official SAM 2 package first.") from error

    if not torch.cuda.is_available():
        raise VisionUnavailable("SAM 2 provider requires CUDA. Use the color trace without a GPU.")
    identifier = os.getenv("GEOFATHOM_SAM2_MODEL_ID", "facebook/sam2.1-hiera-small")
    return SAM2ImagePredictor.from_pretrained(identifier)


def sam_mask(image: np.ndarray, seed_x: int, seed_y: int,
             positive=None, negative=None, box=None) -> tuple[np.ndarray, float, str]:
    """Infer a click-conditioned mask on the supplied RGB window."""
    if not sam_enabled():
        raise VisionUnavailable("SAM 2 is disabled.")
    if (not isinstance(image,np.ndarray) or image.ndim!=3 or image.shape[2]!=3
            or image.dtype!=np.uint8 or not image.size):
        raise ValueError("SAM image must be a nonempty uint8 RGB array.")
    import torch
    positive = positive if positive is not None else [[seed_x, seed_y]]
    negative = negative if negative is not None else []
    prompts = np.asarray([*positive,*negative], dtype=np.float32)
    labels = np.asarray([1]*len(positive)+[0]*len(negative), dtype=np.int32)
    with _predict_lock, torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor = _predictor()
        predictor.set_image(image)
        masks, scores, _ = predictor.predict(
            point_coords=prompts,
            point_labels=labels,
            box=np.asarray(box, dtype=np.float32) if box is not None else None,
            multimask_output=True,
        )
        masks, scores = np.asarray(masks), np.asarray(scores)
        if (masks.ndim!=3 or masks.shape[1:]!=image.shape[:2] or scores.ndim!=1
                or len(scores)!=len(masks) or not scores.size or not np.isfinite(scores).all()
                or not np.isfinite(masks).all()):
            raise RuntimeError("SAM returned invalid mask or confidence tensors.")
        index = int(np.argmax(scores))
        result = np.array(masks[index], dtype=np.uint8, copy=True)
        confidence = float(scores[index])
    return (
        result,
        confidence,
        os.getenv("GEOFATHOM_SAM2_MODEL_ID", "facebook/sam2.1-hiera-small"),
    )
