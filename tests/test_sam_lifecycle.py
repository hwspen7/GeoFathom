"""SAM predictor interface validation and concurrent image isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
import sys
import time

import numpy as np
import pytest
from vision import sam


@pytest.fixture
def sam_backend(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED", "1")
    torch = SimpleNamespace(inference_mode=nullcontext, bfloat16=object(),
                            autocast=lambda *a, **kw: nullcontext())
    monkeypatch.setitem(sys.modules, "torch", torch)
    class Predictor:
        def set_image(self, image):
            self.image = image
            # Force overlapping calls without serialization.
            time.sleep(.005)
        def predict(self, **kwargs):
            value = int(self.image[0, 0, 0])
            masks = np.zeros((2, *self.image.shape[:2]), np.uint8)
            masks[1].fill(value)
            return masks, np.array([.2, .8]), None
    predictor = Predictor()
    monkeypatch.setattr(sam, "_predictor", lambda: predictor)
    return predictor


def test_sam_shared_predictor_keeps_concurrent_images_separate(sam_backend):
    def run(value):
        rgb = np.full((12, 12, 3), value, np.uint8)
        mask, confidence, _ = sam.sam_mask(rgb, 2, 2)
        assert confidence == pytest.approx(.8)
        return int(mask[0, 0])
    inputs = [0, 1] * 12
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(run, inputs)) == inputs


def test_sam_rejects_disabled_and_bad_image(sam_backend, monkeypatch):
    with pytest.raises(ValueError, match="RGB"):
        sam.sam_mask(np.zeros((8, 8)), 0, 0)
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED", "0")
    with pytest.raises(sam.VisionUnavailable, match="disabled"):
        sam.sam_mask(np.zeros((8, 8, 3), np.uint8), 0, 0)


@pytest.mark.parametrize("masks,scores", [
    (np.zeros((1, 7, 8)), np.array([1.])),
    (np.zeros((1, 8, 8)), np.array([np.nan])),
    (np.zeros((0, 8, 8)), np.array([])),
])
def test_sam_rejects_invalid_model_output(sam_backend, monkeypatch, masks, scores):
    monkeypatch.setattr(sam_backend, "predict", lambda **kw: (masks, scores, None))
    with pytest.raises(RuntimeError, match="invalid mask"):
        sam.sam_mask(np.zeros((8, 8, 3), np.uint8), 0, 0)
