"""Learned-head roles, touching roofs, holes and cross-block instance identity."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from imagery.raster import RasterError
from vision.building_instances import separate_instances, instance_raster


def test_boundary_head_separates_touching_roofs_without_losing_foreground():
    mask = np.zeros((80, 120), bool)
    mask[10:70, 10:110] = True
    boundary = np.zeros(mask.shape, np.float32)
    boundary[:, 59:62] = .99
    result = separate_instances(mask, mask.astype(np.float32)*.9, boundary, seed_distance=6)
    assert result.max() == 2
    assert result[40, 30] != result[40, 90]
    np.testing.assert_array_equal(result > 0, mask)
    np.testing.assert_array_equal(result, separate_instances(mask, mask.astype(np.float32)*.9, boundary, seed_distance=6))


def test_courtyard_holes_and_detached_inner_building_are_not_filled():
    mask = np.zeros((100, 100), bool)
    mask[10:90, 10:90] = True
    mask[30:70, 30:70] = False
    mask[45:55, 45:55] = True
    result = separate_instances(mask, mask.astype(np.float32)*.9)
    assert result[35, 35] == 0 and result[50, 50] > 0
    assert result[50, 50] != result[20, 20]
    np.testing.assert_array_equal(result > 0, mask)


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -1., 1.1])
def test_invalid_boundary_probabilities_are_rejected(invalid):
    with pytest.raises(RasterError):
        separate_instances(np.ones((8, 8), bool), np.ones((8, 8), np.float32),
                           np.full((8, 8), invalid, np.float32))


def test_global_component_and_nested_bounds_survive_disk_blocks(tmp_path):
    mask = np.zeros((270, 290), np.uint8)
    mask[30:240, 20:270] = 1
    mask[70:200, 70:220] = 0
    mask[110:160, 120:170] = 1
    profile = dict(driver="GTiff", height=270, width=290, count=1, crs="EPSG:32617",
                   transform=from_origin(500000, 4500000, 1, 1), tiled=True, blockxsize=128, blockysize=128)
    a, b, out = tmp_path/"mask.tif", tmp_path/"probability.tif", tmp_path/"instances.tif"
    with rasterio.open(a, "w", dtype="uint8", nodata=255, **profile) as dst:
        dst.write(mask, 1)
    with rasterio.open(b, "w", dtype="float32", nodata=-1., **profile) as dst:
        dst.write(mask.astype(np.float32)*.9, 1)
    result = instance_raster(a, b, out)
    assert result["connected_components"] == 2
    with rasterio.open(out) as src:
        labels = src.read(1)
        np.testing.assert_array_equal(labels > 0, mask > 0)
        assert labels[130, 140] > 0 and labels[80, 80] == 0
    with pytest.raises(RasterError, match="memory"):
        instance_raster(a, b, tmp_path/"limited.tif", memory_mb=1)

def test_component_local_normalization_matches_independent_roof_partitions():
    from vision.building_instances import separate_components
    mask = np.zeros((96, 160), bool)
    mask[4:76, 4:76] = True
    mask[80:92, 120:154] = True
    boundary = np.zeros(mask.shape, np.float32)
    boundary[80:92, 136:138] = .99
    probability = mask.astype(np.float32)*.9
    result = separate_components(mask, probability, boundary, seed_distance=4)
    local = separate_instances(mask[80:92, 120:154], probability[80:92, 120:154],
                               boundary[80:92, 120:154], seed_distance=4)
    assert local.max() == 2
    assert len(np.unique(result[80:92, 120:154])) == 2
    np.testing.assert_array_equal(result > 0, mask)


def test_four_view_fusion_inverts_all_heads_without_shifting_pixels(monkeypatch):
    from vision import semantic
    tensor = np.arange(60, dtype=np.float32).reshape(1, 3, 4, 5) / 60
    calls = []
    def predict(value, config, device):
        assert value.flags.c_contiguous
        calls.append(value.copy())
        return {"probability": value[0, 0], "boundary": value[0, 1],
                "distance": value[0, 2]*2-1}
    monkeypatch.setattr(semantic, "predict_building_heads", predict)
    result = semantic.fuse_building_heads(tensor, {}, "cpu", augmentation="flips")
    assert len(calls) == 4
    for name, expected in zip(("probability", "boundary", "distance"),
                              (tensor[0, 0], tensor[0, 1], tensor[0, 2]*2-1)):
        np.testing.assert_array_equal(result[name], expected)


def test_four_view_fusion_checks_cancellation_between_passes(monkeypatch):
    from vision import semantic
    calls = []
    def predict(value, config, device):
        calls.append(1)
        return {"probability": value[0, 0]}
    def check():
        if len(calls) == 2:
            raise RuntimeError("cancelled")
    monkeypatch.setattr(semantic, "predict_building_heads", predict)
    with pytest.raises(RuntimeError, match="cancelled"):
        semantic.fuse_building_heads(np.zeros((1, 3, 8, 8), np.float32), {}, "cpu",
                                     augmentation="flips", check=check)
    assert len(calls) == 2


def test_multiscale_fusion_preserves_pixel_centers_and_native_auxiliary_heads(monkeypatch):
    from vision import semantic
    rows, cols = np.indices((48, 64), dtype=np.float32)
    ramp = .1 + rows*.003 + cols*.004
    tensor = np.stack([ramp, ramp, ramp])[None]
    seen = []
    def predict(value, config, device):
        seen.append(value.copy())
        return {"probability": value[0, 0].copy(), "boundary": value[0, 1].copy(),
                "distance": value[0, 2].copy()}
    monkeypatch.setattr(semantic, "predict_building_heads", predict)
    result = semantic.fuse_building_heads(tensor, {}, "cpu", augmentation="multiscale")
    assert len(seen) == 3 and not np.array_equal(seen[0], seen[1])
    np.testing.assert_allclose(result["probability"], ramp, atol=2e-7)
    np.testing.assert_array_equal(result["boundary"], ramp)
    np.testing.assert_array_equal(result["distance"], ramp)


def test_multiscale_fusion_has_native_fallback_outside_zoom_support(monkeypatch):
    from vision import semantic
    calls = []
    def predict(value, config, device):
        calls.append(1)
        return {"probability": np.full(value.shape[-2:], .2 if len(calls)==1 else .8, np.float32)}
    monkeypatch.setattr(semantic, "predict_building_heads", predict)
    result = semantic.fuse_building_heads(np.zeros((1, 3, 64, 64), np.float32), {}, "cpu",
                                          augmentation="multiscale")["probability"]
    assert result[0, 0] == pytest.approx(.2)
    assert result[32, 32] == pytest.approx(.5)
    assert np.all((result >= .2-1e-7) & (result <= .5+1e-7))


def test_adaptive_seed_spacing_retains_nearby_small_roof_peak():
    from vision.building_seeds import select_seeds
    radii = np.ones((24, 24), np.float32)
    radii[10,10]=8
    radii[10,14]=2
    candidates=[(.9,10,10),(.6,10,14)]
    assert select_seeds(candidates,radii,6)==[(10,10)]
    assert select_seeds(candidates,radii,6,adaptive=True)==[(10,10),(10,14)]


def test_adaptive_instances_preserve_foreground_holes_and_separate_narrow_adjacent_roof():
    from vision.building_instances import separate_components
    mask=np.zeros((40,48),bool)
    mask[8:32,4:28]=True
    mask[17:23,28:36]=True
    mask[12:15,8:11]=False
    boundary=np.zeros(mask.shape,np.float32)
    boundary[17:23,27:29]=.95
    p=mask.astype(np.float32)*.9
    labels=separate_components(mask,p,boundary,seed_distance=16,adaptive=True)
    np.testing.assert_array_equal(labels>0,mask)
    assert labels[20,32] != labels[20,20]
    assert labels[20,32]>0
    np.testing.assert_array_equal(labels,separate_components(mask,p,boundary,seed_distance=16,adaptive=True))
