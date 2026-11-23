"""Independent numerical research-workflow tests, including real GeoTIFF/ZIP bytes."""
import base64
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from pyproj import Transformer

from imagery.raster import RasterError
from terrain.research import (
    ahp_weights, analyze_research, checkpoint_accuracy, verify_research_bundle, replay_research_bundle,
)


def create_grid(tmp_path):
    transform = from_origin(500000, 4500000, 10, 10)
    yy, xx = np.indices((14, 14), dtype=np.float32)
    main = np.full((14, 14), 100., dtype=np.float32)
    x = xx.copy()
    y = yy.copy()
    y[5, 5] = -9999
    paths = []
    for name, array in (("dem", main), ("longitude", x), ("latitude", y)):
        path = tmp_path / (name + ".tif")
        with rasterio.open(path, "w", driver="GTiff", width=14, height=14,
                           count=1, dtype="float32", nodata=-9999,
                           crs="EPSG:32617", transform=transform) as out:
            out.write(array, 1)
            if name == "dem":
                out.update_tags(VERTICAL_DATUM="NAVD88", VERTICAL_UNIT="meter")
        paths.append(path)
    convert = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)
    # Keep a one-cell buffer inside the known raster grid.
    projected = [(500010, 4499990), (500130, 4499990),
                 (500130, 4499870), (500010, 4499870), (500010, 4499990)]
    polygon = {"type": "Polygon",
               "coordinates": [[convert.transform(*point) for point in projected]]}
    return paths, polygon, transform


def inputs(paths):
    return [
        {"path": paths[1], "name": "X", "low": 0, "high": 13,
         "direction": "increasing", "weight": 3, "sigma": .3, "weight_sigma": .15},
        {"path": paths[2], "name": "Y", "low": 0, "high": 13,
         "direction": "decreasing", "weight": 1, "sigma": .2, "weight_sigma": .1},
    ]


def decode(result):
    raw = base64.b64decode(result["archive_base64"], validate=True)
    with ZipFile(BytesIO(raw)) as bundle:
        with MemoryFile(bundle.read("outputs/suitability.tif")) as mem:
            with mem.open() as product:
                scores = product.read(1)
                crs = str(product.crs)
                nodata = product.nodata
        with MemoryFile(bundle.read("inputs/criterion-1.tif")) as mem:
            with mem.open() as raster:
                x = raster.read(1)
        with MemoryFile(bundle.read("inputs/criterion-2.tif")) as mem:
            with mem.open() as raster:
                y = raster.read(1)
        metadata = json.loads(bundle.read("analysis.json"))
    return raw, scores, x, y, crs, nodata, metadata


def test_reciprocal_ahp_weights_and_inconsistency_fail_closed():
    weights, diagnostics = ahp_weights([[1, 2, 4], [.5, 1, 2], [.25, .5, 1]])
    np.testing.assert_allclose(weights, [4 / 7, 2 / 7, 1 / 7], atol=1e-10)
    assert diagnostics["consistency_ratio"] < 1e-8
    with pytest.raises(RasterError, match="reciprocal"):
        ahp_weights([[1, 3], [3, 1]])
    with pytest.raises(RasterError, match="consistency"):
        ahp_weights([[1, 9, 1], [1 / 9, 1, 9], [1, 1 / 9, 1]])
    with pytest.raises(RasterError, match="positive"):
        ahp_weights([[1, 0], [0, 1]])


def test_joint_nodata_exclusion_and_correct_weighted_cell_scores(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    output = analyze_research(paths[0], polygon, inputs(paths),
                              {"trials": 0, "threshold": .5})
    raw, score, x, y, crs, nodata, metadata = decode(output)
    assert crs == "EPSG:32617"
    assert np.isnan(nodata)
    valid = np.isfinite(score)
    expected = .75 * np.clip(x / 13, 0, 1) + .25 * np.clip((13 - y) / 13, 0, 1)
    np.testing.assert_allclose(score[valid], expected[valid], atol=1e-6, rtol=0)
    assert output["metrics"]["eligible_cells"] == int(valid.sum())
    assert np.isnan(score).any()  # outside geometry and NoData excluded
    assert metadata["model"]["weights"] == pytest.approx([.75, .25])
    assert output["metrics"]["eligible_above_threshold_area_m2"] == pytest.approx(
        (score[valid] >= .5).sum() * 100)
    assert output["raster_names"] == ["suitability"]
    assert verify_research_bundle(raw)["valid"]


def test_ahp_criteria_constraints_and_zero_valid_grid(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    factors = inputs(paths)
    factors[0]["allowed_min"] = 4
    factors[0]["allowed_max"] = 7
    run = analyze_research(paths[0], polygon, factors,
                           {"pairwise": [[1, 2], [.5, 1]], "trials": 0})
    assert run["model"]["ahp"]["consistent"]
    assert run["model"]["weights"] == pytest.approx([2 / 3, 1 / 3])
    assert run["metrics"]["eligible_cells"] < run["metrics"]["valid_primary_cells"]
    factors[0]["allowed_min"] = 1000
    factors[0]["allowed_max"] = None
    with pytest.raises(RasterError, match="Fewer than three"):
        analyze_research(paths[0], polygon, factors, {"trials": 0})


def test_uncertainty_seed_reproducibility_and_variable_noise(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    config = {"trials": 24, "seed": 321, "threshold": .5}
    first = analyze_research(paths[0], polygon, inputs(paths), config)
    second = analyze_research(paths[0], polygon, inputs(paths), config)
    assert first["archive_sha256"] == second["archive_sha256"]
    assert first["metrics"] == second["metrics"]
    assert len(first["sensitivity"]) == 4
    assert first["model"]["uncertainty"]["score_sd_mean"] > 0
    raw = base64.b64decode(first["archive_base64"])
    with ZipFile(BytesIO(raw)) as archive:
        with MemoryFile(archive.read("outputs/ensemble_frequency.tif")) as mem:
            with mem.open() as ds:
                probability = ds.read(1)
        with MemoryFile(archive.read("outputs/ensemble_sd.tif")) as mem:
            with mem.open() as ds:
                uncertainty = ds.read(1)
    assert ((probability[np.isfinite(probability)] >= 0)
            & (probability[np.isfinite(probability)] <= 1)).all()
    assert (uncertainty[np.isfinite(uncertainty)] > 0).any()
    other = analyze_research(paths[0], polygon, inputs(paths), {**config, "seed": 322})
    assert first["archive_sha256"] != other["archive_sha256"]


def test_zero_error_mc_remains_deterministic(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    factors = inputs(paths)
    for item in factors:
        item["sigma"] = 0
        item["weight_sigma"] = 0
    result = analyze_research(paths[0], polygon, factors, {"trials": 8})
    assert result["model"]["uncertainty"]["score_sd_mean"] == pytest.approx(0, abs=1e-12)


def test_archive_checksum_verifies_each_member_and_rejects_corruption(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    data = base64.b64decode(analyze_research(
        paths[0], polygon, inputs(paths), {"trials": 0})["archive_base64"])
    with ZipFile(BytesIO(data)) as bundle:
        files = {name: bundle.read(name) for name in bundle.namelist()}
    files["outputs/suitability.tif"] = files["outputs/suitability.tif"] + b"tampered"
    changed = BytesIO()
    with ZipFile(changed, "w", compression=ZIP_DEFLATED) as target:
        for name, payload in files.items():
            target.writestr(name, payload)
    with pytest.raises(RasterError, match="checksum"):
        verify_research_bundle(changed.getvalue())


def test_validation_checkpoints_descriptive_errors_and_vertical_datum(tmp_path):
    paths, _, transform = create_grid(tmp_path)
    to_wgs84 = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)
    checkpoints = []
    for j, residual in enumerate([1., -2., 0., 3., -1., 0.]):
        x, y = transform * (j + 2.5, 4.5)
        lon, lat = to_wgs84.transform(x, y)
        checkpoints.append({"longitude": lon, "latitude": lat,
                            "elevation_m": 100. - residual})
    report = checkpoint_accuracy(paths[0], checkpoints, "NAVD88")
    errors = np.asarray([1., -2., 0., 3., -1., 0.])
    assert report["datum_verified"]
    assert report["sample_count"] == 6
    assert report["rmse_m"] == pytest.approx(np.sqrt(np.mean(errors**2)))
    assert report["mean_error_m"] == pytest.approx(errors.mean())
    assert report["mae_m"] == pytest.approx(np.mean(np.abs(errors)))
    assert report["nmad_m"] == pytest.approx(
        1.4826 * np.median(np.abs(errors - np.median(errors))))
    with pytest.raises(RasterError, match="datum"):
        checkpoint_accuracy(paths[0], checkpoints, "EGM96")
    without_reference = checkpoint_accuracy(paths[0], checkpoints)
    assert not without_reference["datum_verified"]


@pytest.mark.parametrize("invalid", [
    {"trials": 257}, {"seed": -1}, {"threshold": 2},
    {"sensitivity_fraction": 0}, {"trials": True},
])
def test_invalid_simulation_contract_fails(tmp_path, invalid):
    paths, geometry, _ = create_grid(tmp_path)
    with pytest.raises(RasterError):
        analyze_research(paths[0], geometry, inputs(paths), invalid)


def test_cannot_interpolate_categorical_rasters_without_explicit_nearest(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    factors = inputs(paths)
    factors[0]["direction"] = "target"
    factors[0]["target"] = 6
    factors[0]["sampling"] = "nearest"
    run = analyze_research(paths[0], polygon, factors, {"trials": 0})
    assert run["sources"][0]["interpolation"] == "nearest"
    assert run["metrics"]["score_mean"] >= 0


def test_portable_replay_recomputes_nominal_and_seeded_ensemble(tmp_path):
    paths, polygon, _ = create_grid(tmp_path)
    model = analyze_research(paths[0], polygon, inputs(paths),
                             {"trials": 16, "seed": 882, "threshold": .55})
    archived = base64.b64decode(model["archive_base64"], validate=True)
    replayed = replay_research_bundle(archived)
    assert replayed["reproducible"]
    assert set(replayed["outputs"]) == {
        "suitability", "ensemble_mean", "ensemble_sd", "ensemble_frequency"}
    assert max(replayed["outputs"].values()) < 2e-6
    assert replayed["verified_files"] == len(model["archive_manifest"]["files"])


def test_replay_rejects_bitwise_valid_but_scientifically_wrong_product(tmp_path):
    """A forged but internally checksummed archive must fail numerical replay."""
    from hashlib import sha256
    paths, polygon, _ = create_grid(tmp_path)
    model = analyze_research(paths[0], polygon, inputs(paths), {"trials": 0})
    original = base64.b64decode(model["archive_base64"])
    with ZipFile(BytesIO(original)) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    with MemoryFile(entries["outputs/suitability.tif"]) as mem:
        with mem.open() as ds:
            values = ds.read(1)
            valid = np.isfinite(values)
            values[valid] = .17
            spec = dict(driver="GTiff",width=ds.width,height=ds.height,count=1,
                        dtype="float32",crs=ds.crs,transform=ds.transform,
                        nodata=float("nan"),compress="deflate")
        with MemoryFile() as replacement:
            with replacement.open(**spec) as dst:
                dst.write(values, 1)
            entries["outputs/suitability.tif"] = replacement.read()
    manifest = json.loads(entries["manifest.json"])
    payload = entries["outputs/suitability.tif"]
    manifest["files"]["outputs/suitability.tif"] = {
        "sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
    entries["manifest.json"] = json.dumps(manifest).encode("utf8")
    rebuilt = BytesIO()
    with ZipFile(rebuilt, "w", compression=ZIP_DEFLATED) as zipfile:
        for name, payload in entries.items():
            zipfile.writestr(name, payload)
    forged = rebuilt.getvalue()
    assert verify_research_bundle(forged)["valid"]
    with pytest.raises(RasterError, match="Scientific replay values differ"):
        replay_research_bundle(forged)
