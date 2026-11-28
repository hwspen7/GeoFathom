"""Local Pix2Poly acceleration without changing the upstream greedy decoder.

Cache only the image encoder output, retaining every autoregressive decoder
step, token confidence, and the final upstream permutation assignment.
"""
from contextlib import contextmanager


@contextmanager
def cached_encoder(model,image):
    """The upstream generator repeatedly calls model.predict(image, tokens).

    This context is single-image, inference-only and not thread safe. Restore
    the original method even when generation fails; never reuse another image.
    """
    import torch
    if model.training or torch.is_grad_enabled():
        raise ValueError("Encoder caching requires evaluation and disabled gradients.")
    original=model.predict
    features=model.encoder(image)
    def predict(same_image,tokens):
        if (same_image.data_ptr()!=image.data_ptr() or same_image.shape!=image.shape
                or same_image.device!=image.device or same_image.dtype!=image.dtype):
            raise ValueError("Cached encoder cannot accept another image.")
        return model.decoder.predict(features,tokens)
    model.predict=predict
    try:
        yield
    finally:
        model.predict=original


def configure_variant(config,variant):
    """Official checkpoint families use different maximum vertex capacities."""
    capacities={"inria":192,"spacenet":192,"whu":144}
    if variant not in capacities:
        raise ValueError("Unsupported building checkpoint family.")
    if (config.INPUT_HEIGHT,config.INPUT_WIDTH,config.PATCH_SIZE,config.NUM_BINS)!=(224,224,8,224):
        raise ValueError("Pinned Pix2Poly spatial configuration changed.")
    config.N_VERTICES=capacities[variant]
    config.MAX_LEN=2*config.N_VERTICES+2
    config.generation_steps=config.MAX_LEN-1
    return config
