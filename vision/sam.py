"""Optional promptable SAM 2.1 image segmentation.

The user must deliberately enable SAM and install its dependencies.
No model is downloaded during normal API startup or the color trace path.
"""

import os
from functools import lru_cache

import numpy as np


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
    predictor = _predictor()
    import torch
    positive = positive if positive is not None else [[seed_x, seed_y]]
    negative = negative if negative is not None else []
    prompts = np.asarray([*positive,*negative], dtype=np.float32)
    labels = np.asarray([1]*len(positive)+[0]*len(negative), dtype=np.int32)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor.set_image(image)
        masks, scores, _ = predictor.predict(
            point_coords=prompts,
            point_labels=labels,
            box=np.asarray(box, dtype=np.float32) if box is not None else None,
            multimask_output=True,
        )
    index = int(np.argmax(scores))
    return (
        np.asarray(masks[index], dtype=np.uint8),
        float(scores[index]),
        os.getenv("GEOFATHOM_SAM2_MODEL_ID", "facebook/sam2.1-hiera-small"),
    )
