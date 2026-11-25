"""C++/NumPy spectral raster parity, nodata and input-contract tests."""
import os
import time

import numpy as np
import pytest

import geometry.spectral as spectral
from geometry.topology import _native


def _run_both(monkeypatch, func, *args):
    native = func(*args)
    with monkeypatch.context() as context:
        context.setattr(spectral, "_native", lambda: None)
        python = func(*args)
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE") == "1":
        assert native[-1] == "cpp-spectral"
    assert python[-1] == "numpy-spectral"
    return native, python


def test_normalized_difference_cpp_matches_numpy_over_masked_float_rasters(monkeypatch):
    rng = np.random.default_rng(2026)
    first = rng.uniform(1, 10000, size=(193, 257)).astype("float32")
    second = rng.uniform(1, 10000, size=(193, 257)).astype("float32")
    mask = rng.integers(0, 2, size=first.shape, dtype=np.uint8)
    first[0, 0] = np.nan
    second[0, 1] = np.inf
    first[0, 2] = -second[0, 2]
    first[0, 3] = 0
    second[0, 3] = 0
    # Exercise non-contiguous NumPy views crossing the C ABI.
    native, fallback = _run_both(
        monkeypatch, spectral.normalized_difference,
        first[:, ::2], second[:, ::2], mask[:, ::2])
    np.testing.assert_array_equal(native[1], fallback[1])
    np.testing.assert_allclose(native[0], fallback[0], atol=1e-6, rtol=1e-6)
    assert not native[1][0, 0]
    assert not native[1][0, 1]
    assert native[0][0, 0] == 0


def test_normalized_difference_known_values_and_input_rejection():
    a = np.array([[200, 100, 0], [50, np.nan, 50]], dtype=np.float32)
    b = np.array([[100, 100, 0], [50, 1, -50]], dtype=np.float32)
    mask = np.ones((2, 3), dtype=np.uint8)
    result, valid, _ = spectral.normalized_difference(a, b, mask)
    assert result[0, 0] == pytest.approx(1 / 3, abs=1e-6)
    assert valid[0, 0] and valid[0, 1] and valid[1, 0]
    assert not valid[0, 2] and not valid[1, 1] and not valid[1, 2]
    assert np.all(result[~valid] == 0)
    with pytest.raises(ValueError, match="equally sized"):
        spectral.normalized_difference(a, b[:, :2], mask)
    with pytest.raises(ValueError, match="equally sized"):
        spectral.normalized_difference(a[:0], b[:0], mask[:0])


def test_change_cpp_matches_numpy_at_threshold_edges_and_invalid_cells(monkeypatch):
    rng = np.random.default_rng(401)
    old = rng.uniform(-1, 1, size=(107, 149)).astype("float32")
    new = rng.uniform(-1, 1, size=(107, 149)).astype("float32")
    old_valid = rng.integers(0, 2, size=old.shape, dtype=np.uint8)
    new_valid = rng.integers(0, 2, size=old.shape, dtype=np.uint8)
    old[0, 0] = np.nan
    new[0, 1] = np.inf
    old_valid[0, 2] = 0
    new_valid[0, 2] = 0
    before, fallback = _run_both(
        monkeypatch, spectral.classify_change,
        old, old_valid, new, new_valid, .25)
    np.testing.assert_array_equal(before[0], fallback[0])
    assert before[0][0, 0] == 0 and before[0][0, 1] == 0
    assert before[0][0, 2] == 0
    known = np.array([[0, 0, 0]], dtype=np.float32)
    changed = np.array([[.5, -.5, .1]], dtype=np.float32)
    result, _ = spectral.classify_change(known, np.ones((1, 3), np.uint8),
                                        changed, np.ones((1, 3), np.uint8), .2)
    assert result.tolist() == [[1, 2, 0]]
    with pytest.raises(ValueError, match="threshold"):
        spectral.classify_change(old, old_valid, new, new_valid, 0)
    with pytest.raises(ValueError, match="pixel grid"):
        spectral.classify_change(old, old_valid, new, new_valid[:, :2], .25)


def test_native_spectral_large_raster_smoke_without_strict_timing_assumptions():
    # A functional stress test; fixed speedup assertions would be flaky
    # across shared CI runners with different CPU throttling and SIMD.
    pixels = np.full((768, 768), 150, dtype=np.float32)
    mask = np.ones_like(pixels, dtype=np.uint8)
    start = time.perf_counter()
    index, usable, engine = spectral.normalized_difference(pixels * 2, pixels, mask)
    after = np.zeros_like(index)
    labels, change_engine = spectral.classify_change(after, usable, index, usable, .1)
    elapsed = time.perf_counter() - start
    assert index.shape == pixels.shape
    assert usable.sum() == 768 * 768
    assert np.count_nonzero(labels == 1) == 768 * 768
    assert elapsed < 15
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE") == "1":
        assert engine == "cpp-spectral"
        assert change_engine == "cpp-spectral"
