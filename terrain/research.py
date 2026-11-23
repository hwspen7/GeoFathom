"""Reproducible, bounded GIS multicriteria evaluation and uncertainty screening.

Scope: explicit linear value functions, independent cellwise input perturbations,
and deterministic OAT weight sensitivity. Results are screening evidence, NOT
a calibrated physical-risk model or inferential confidence intervals.
"""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, BadZipFile

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import reproject, Resampling

from imagery.raster import RasterError
from imagery.store import file_sha256
from .advanced import _window
from .cancellation import checkpoint
from .engine import _check_dem
from .vertical import vertical_datum, check_vertical_compatibility

SCHEMA = "geofathom.research.v1"
MAX_CRITERIA = 8
MAX_GRID_CELLS = 1_000_000
MAX_TRIALS = 256
RI = {1: 0., 2: 0., 3: .58, 4: .90, 5: 1.12, 6: 1.24,
      7: 1.32, 8: 1.41}


def _finite(value, name):
    if isinstance(value, bool):
        raise RasterError(f"{name} must be a finite number.")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise RasterError(f"{name} must be a finite number.") from exc
    if not math.isfinite(result):
        raise RasterError(f"{name} must be a finite number.")
    return result


def ahp_weights(pairwise):
    """Principal right eigenvector and Saaty consistency ratio, with strict reciprocity."""
    matrix = np.asarray(pairwise, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise RasterError("AHP requires a square pairwise matrix.")
    n = matrix.shape[0]
    if not 1 <= n <= MAX_CRITERIA or not np.isfinite(matrix).all() or (matrix <= 0).any():
        raise RasterError("AHP requires 1–8 positive, finite criteria.")
    if not np.allclose(np.diag(matrix), 1., atol=1e-9, rtol=0):
        raise RasterError("AHP diagonal values must be one.")
    if not np.allclose(matrix * matrix.T, 1., atol=1e-8, rtol=1e-8):
        raise RasterError("AHP comparisons must be reciprocal.")
    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    idx = int(np.argmax(eigenvalues.real))
    maximum = float(eigenvalues[idx].real)
    vector = eigenvectors[:, idx].real
    if vector.sum() < 0:
        vector = -vector
    if np.any(vector <= 0):
        raise RasterError("AHP weights are not positive.")
    weights = vector / vector.sum()
    ci = max(0., (maximum - n) / (n - 1)) if n > 1 else 0.
    ratio = ci / RI[n] if RI[n] else 0.
    if ratio > .1 + 1e-9:
        raise RasterError(f"AHP consistency ratio {ratio:.4f} exceeds 0.10; revise the comparisons.")
    return weights, {"consistency_ratio": ratio, "lambda_max": maximum,
                     "consistent": True, "criteria_count": n}


def _criterion_config(raw, i):
    if not isinstance(raw, dict):
        raise RasterError(f"Criterion {i + 1} must be an object.")
    name = str(raw.get("name", "")).strip()
    if not 1 <= len(name) <= 80:
        raise RasterError("Every criterion requires a 1–80 character name.")
    low = _finite(raw.get("low"), name + " low")
    high = _finite(raw.get("high"), name + " high")
    if not low < high:
        raise RasterError(f"{name}: high must exceed low.")
    direction = raw.get("direction")
    if direction not in {"increasing", "decreasing", "target"}:
        raise RasterError(f"{name}: select increasing, decreasing or target.")
    target = _finite(raw.get("target"), name + " target") if direction == "target" else None
    if target is not None and not low < target < high:
        raise RasterError(f"{name}: target must lie strictly inside the anchors.")
    weight = _finite(raw.get("weight", 1.), name + " weight")
    sigma = _finite(raw.get("sigma", 0.), name + " sigma")
    weight_sigma = _finite(raw.get("weight_sigma", 0.), name + " weight sigma")
    if weight <= 0 or sigma < 0 or weight_sigma < 0 or weight_sigma > 1:
        raise RasterError(f"{name}: weights must be positive, uncertainties nonnegative; weight sigma <= 1.")
    allowed_min = raw.get("allowed_min")
    allowed_max = raw.get("allowed_max")
    if allowed_min is not None:
        allowed_min = _finite(allowed_min, name + " minimum constraint")
    if allowed_max is not None:
        allowed_max = _finite(allowed_max, name + " maximum constraint")
    if allowed_min is not None and allowed_max is not None and allowed_min > allowed_max:
        raise RasterError(f"{name}: invalid hard constraint interval.")
    sampling = raw.get("sampling", "bilinear")
    if sampling not in {"nearest", "bilinear"}:
        raise RasterError(f"{name}: only nearest or bilinear resampling is supported.")
    return {"name": name, "low": low, "high": high, "direction": direction,
            "target": target, "weight": weight, "sigma": sigma,
            "weight_sigma": weight_sigma, "allowed_min": allowed_min,
            "allowed_max": allowed_max, "sampling": sampling,
            "vertical_elevation": bool(raw.get("vertical_elevation", False))}


def _utility(data, criterion):
    low, high = criterion["low"], criterion["high"]
    if criterion["direction"] == "increasing":
        score = (data - low) / (high - low)
    elif criterion["direction"] == "decreasing":
        score = (high - data) / (high - low)
    else:
        target = criterion["target"]
        score = np.where(data <= target, (data - low) / (target - low),
                         (high - data) / (high - target))
    return np.clip(score, 0., 1.)


def _weighted(utilities, weights, valid):
    score = np.zeros(valid.shape, dtype=np.float64)
    for utility, weight in zip(utilities, weights):
        score += weight * utility
    return np.where(valid, score, np.nan)


def _geotiff(data, affine, crs, operation, unit):
    finite = np.asarray(data, dtype=np.float32)
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=finite.shape[1], height=finite.shape[0],
                      count=1, dtype="float32", crs=crs, transform=affine,
                      nodata=float("nan"), compress="deflate") as dst:
            dst.write(finite, 1)
            dst.update_tags(RESEARCH_SCHEMA=SCHEMA, RESEARCH_PRODUCT=operation,
                            RESEARCH_UNIT=unit, RESEARCH_NODATA_POLICY="NaN")
        return mem.read()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _make_bundle(files, metadata):
    """Content-address every archived input and output (not only a screenshot)."""
    metadata_bytes = _canonical(metadata)
    contents = {**files, "analysis.json": metadata_bytes}
    manifest = {"schema": SCHEMA, "hash_algorithm": "SHA-256",
                "files": {name: {"sha256": sha256(payload).hexdigest(),
                                 "bytes": len(payload)}
                          for name, payload in sorted(contents.items())},
                "replay_note": "Aligned input rasters are included; original acquisition files are identified by SHA-256 but are not included."}
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        for name, payload in sorted(contents.items()):
            bundle.writestr(name, payload)
        bundle.writestr("manifest.json", _canonical(manifest))
    return stream.getvalue(), manifest


def verify_research_bundle(data):
    """Strictly verify names, individual hashes, sizes and required files."""
    try:
        with ZipFile(BytesIO(data), "r") as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)) or any(
                n.startswith("/") or ".." in n.split("/") or "\\" in n for n in names
            ):
                raise RasterError("Research archive contains unsafe or duplicate paths.")
            if "manifest.json" not in names or "analysis.json" not in names:
                raise RasterError("Research archive is missing a manifest or analysis.")
            manifest = json.loads(bundle.read("manifest.json"))
            if manifest.get("schema") != SCHEMA or manifest.get("hash_algorithm") != "SHA-256":
                raise RasterError("Unsupported research manifest.")
            entries = manifest.get("files")
            if not isinstance(entries, dict) or set(entries) != set(names) - {"manifest.json"}:
                raise RasterError("Research archive has missing or untracked files.")
            for name, expected in entries.items():
                payload = bundle.read(name)
                if len(payload) != expected["bytes"] or sha256(payload).hexdigest() != expected["sha256"]:
                    raise RasterError("Research archive checksum mismatch: " + name)
            metadata = json.loads(bundle.read("analysis.json"))
            if metadata.get("schema") != SCHEMA:
                raise RasterError("Research metadata schema mismatch.")
            return {"valid": True, "files": len(entries),
                    "source_sha256": [entry["sha256"] for entry in metadata["sources"]],
                    "model": metadata["model"]}
    except (BadZipFile, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RasterError("Invalid research archive.") from exc


def _open_layer(path, target_shape, affine, crs, config, primary_datum):
    with rasterio.open(path) as src:
        if src.count != 1 or src.crs is None or src.width < 2 or src.height < 2:
            raise RasterError(config["name"] + ": expected one georeferenced raster band.")
        if not np.issubdtype(np.dtype(src.dtypes[0]), np.number):
            raise RasterError(config["name"] + ": raster must be numerical.")
        if config["vertical_elevation"]:
            _check_dem(src)
            check_vertical_compatibility([primary_datum, vertical_datum(src)])
        destination = np.full(target_shape, np.nan, dtype=np.float32)
        reproject(source=rasterio.band(src, 1), destination=destination,
                  src_nodata=src.nodata, dst_nodata=np.nan,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=affine, dst_crs=crs,
                  resampling=Resampling.nearest if config["sampling"] == "nearest" else Resampling.bilinear,
                  num_threads=1, warp_mem_limit=64)
        return destination


def analyze_research(primary_path, geometry, criteria, options=None, cancel=None):
    """GIS-MCDA over a chosen projected DEM grid with explicit model assumptions.

    Each criterion contains a server-resolved path and independently supplied
    utility anchors. NoData in any criterion excludes the cell, never zero-fills.
    Monte Carlo variability is a screening ensemble, not a confidence interval
    or a spatial error-covariance model.
    """
    options = options or {}
    if not isinstance(criteria, list) or not 2 <= len(criteria) <= MAX_CRITERIA:
        raise RasterError("Research analysis requires 2–8 criteria.")
    parsed = [_criterion_config(item, i) for i, item in enumerate(criteria)]
    names = [c["name"] for c in parsed]
    if len(set(names)) != len(names):
        raise RasterError("Criterion names must be unique.")
    threshold = _finite(options.get("threshold", .65), "suitability threshold")
    sensitivity = _finite(options.get("sensitivity_fraction", .2), "weight sensitivity")
    if not 0 <= threshold <= 1 or not 0 < sensitivity <= .5:
        raise RasterError("Threshold must be 0–1 and sensitivity fraction 0–0.5.")
    trials = options.get("trials", 64)
    seed = options.get("seed", 42)
    if isinstance(trials, bool) or not isinstance(trials, int) or not 0 <= trials <= MAX_TRIALS:
        raise RasterError("Monte Carlo trials must be an integer from 0 to 256.")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise RasterError("Random seed must be an unsigned 32-bit integer.")
    z, primary_valid, inside, affine, crs, _boundary, overlap = _window(
        primary_path, geometry, 2048, MAX_GRID_CELLS)
    checkpoint(cancel)
    with rasterio.open(primary_path) as src:
        _check_dem(src)
        primary_datum = vertical_datum(src)
    aligned, source_details = [], []
    for raw, config in zip(criteria, parsed):
        checkpoint(cancel)
        path = Path(raw["path"])
        values = _open_layer(path, z.shape, affine, crs, config, primary_datum)
        aligned.append(values)
        source_details.append({"name": config["name"],
                               "sha256": file_sha256(path),
                               "aligned_grid": [z.shape[1], z.shape[0]],
                               "interpolation": config["sampling"],
                               "vertical_elevation": config["vertical_elevation"]})
    valid = primary_valid.copy()
    for config, values in zip(parsed, aligned):
        valid &= np.isfinite(values)
        if config["allowed_min"] is not None:
            valid &= values >= config["allowed_min"]
        if config["allowed_max"] is not None:
            valid &= values <= config["allowed_max"]
    count = int(valid.sum())
    if count < 3:
        raise RasterError("Fewer than three cells satisfy joint coverage and hard constraints.")
    if "pairwise" in options and options["pairwise"] is not None:
        weights, ahp = ahp_weights(options["pairwise"])
        if len(weights) != len(criteria):
            raise RasterError("AHP matrix dimension must match criteria.")
    else:
        weights = np.array([c["weight"] for c in parsed], dtype=float)
        weights /= weights.sum()
        ahp = None
    utilities = [_utility(a.astype(np.float64), c) for a, c in zip(aligned, parsed)]
    # Utilities may be undefined outside the valid overlap; zero them only for
    # arithmetic, then restore the union-of-unknown NoData mask at output.
    utilities = [np.where(valid, u, 0.) for u in utilities]
    score = _weighted(utilities, weights, valid)
    cell_area = abs(affine.a * affine.e)
    baseline_mean = float(np.mean(score[valid]))
    baseline_pct = 100 * float(np.mean(score[valid] >= threshold))
    sensitivity_results = []
    for i, config in enumerate(parsed):
        checkpoint(cancel)
        for direction in (-1, 1):
            changed = weights.copy()
            changed[i] *= 1 + direction * sensitivity
            changed /= changed.sum()
            scenario = _weighted(utilities, changed, valid)
            sensitivity_results.append({
                "criterion": config["name"], "direction": "down" if direction < 0 else "up",
                "weight": float(changed[i]), "mean_score": float(np.mean(scenario[valid])),
                "eligible_above_threshold_pct": 100 * float(np.mean(scenario[valid] >= threshold)),
                "mean_score_delta": float(np.mean(scenario[valid]) - baseline_mean)})
    outputs = {"suitability": score}
    uncertainty = {"trials": trials, "seed": seed,
                   "assumption": "Independent cellwise Gaussian criterion errors; independent Gaussian relative weight perturbations truncated at zero. Hard constraints fixed at nominal values. Ensemble frequencies are not calibrated probabilities or confidence intervals."}
    if trials:
        rng = np.random.default_rng(seed)
        average = np.zeros(score.shape, dtype=np.float64)
        squared = np.zeros_like(average)
        passed = np.zeros(score.shape, dtype=np.uint16)
        for k in range(trials):
            checkpoint(cancel)
            trial_weights = np.array([max(1.e-9, w * (1 + rng.normal(0, c["weight_sigma"])))
                                      for w, c in zip(weights, parsed)])
            trial_weights /= trial_weights.sum()
            realization = np.zeros(score.shape, dtype=np.float64)
            for values, config, w in zip(aligned, parsed, trial_weights):
                sample = (values.astype(np.float64) + rng.normal(0, config["sigma"], size=values.shape)
                          if config["sigma"] else values.astype(np.float64))
                realization += w * np.where(valid, _utility(sample, config), 0.)
            delta = realization - average
            average += delta / (k + 1)
            squared += delta * (realization - average)
            passed += ((realization >= threshold) & valid).astype(np.uint16)
        outputs.update({"ensemble_mean": np.where(valid, average, np.nan),
                        "ensemble_sd": np.where(valid, np.sqrt(squared / max(1, trials - 1)), np.nan),
                        "ensemble_frequency": np.where(valid, passed.astype(float) / trials, np.nan)})
        uncertainty["above_threshold_frequency_mean"] = float(np.mean(passed[valid] / trials))
        uncertainty["score_sd_mean"] = float(np.mean(np.sqrt(squared[valid] / max(1, trials - 1))))
    checkpoint(cancel)
    metrics = {
        "eligible_cells": count, "study_cells": int(inside.sum()),
        "valid_primary_cells": int(primary_valid.sum()),
        "excluded_or_missing_cells": int(inside.sum()) - count,
        "eligible_area_m2": count * cell_area,
        "eligible_above_threshold_area_m2": float((score[valid] >= threshold).sum() * cell_area),
        "eligible_above_threshold_pct": baseline_pct,
        "score_min": float(score[valid].min()), "score_max": float(score[valid].max()),
        "score_mean": baseline_mean, "source_dem_footprint_overlap_pct": overlap}
    model = {"criteria": [{k: v for k, v in c.items()} for c in parsed],
             "weights": [float(v) for v in weights], "threshold": threshold,
             "sensitivity_fraction": sensitivity,
             "ahp": ahp, "uncertainty": uncertainty}
    files = {}
    for i, values in enumerate(aligned):
        files[f"inputs/criterion-{i + 1}.tif"] = _geotiff(
            np.where(inside, values, np.nan), affine, crs, "aligned_input", "source_units")
    files["inputs/dem.tif"] = _geotiff(np.where(inside, z, np.nan),
                                     affine, crs, "source_dem", "m")
    files["inputs/eligible.tif"] = _geotiff(valid.astype(float),
                                          affine, crs, "eligible_mask", "binary")
    for name, values in outputs.items():
        files[f"outputs/{name}.tif"] = _geotiff(values, affine, crs, name,
                                              "fraction" if name == "ensemble_frequency" else "score")
    metadata = {"schema": SCHEMA, "algorithm": "deterministic_wlc_mcda_v1",
                "source_dem_sha256": file_sha256(primary_path),
                "sources": source_details, "model": model, "metrics": metrics,
                "sensitivity": sensitivity_results,
                "grid": {"crs": str(crs), "transform": list(affine)[:6],
                         "width": z.shape[1], "height": z.shape[0]},
                "limitations": ["Cell-center raster screening, not planning permission or engineering certification.",
                                "Categorical source rasters must use nearest resampling.",
                                "Missing cells are excluded, never substituted as zero.",
                                "Input accuracy and spatial autocorrelation are not inferred.",
                                "Original source files are SHA-256 referenced but not embedded."]}
    archive, manifest = _make_bundle(files, metadata)
    return {"schema": SCHEMA, "metrics": metrics, "model": model, "sources": source_details,
            "sensitivity": sensitivity_results, "archive_base64": base64.b64encode(archive).decode("ascii"),
            "archive_sha256": sha256(archive).hexdigest(),
            "archive_manifest": manifest, "raster_names": list(outputs),
            "warning": "Research screening model; evaluate source accuracy, spatial correlation and independent field validation."}


def checkpoint_accuracy(path, points, declared_datum=None, cancel=None):
    """Independent WGS84 checkpoint diagnostics; checkpoints are user-supplied evidence."""
    from pyproj import Transformer
    if not isinstance(points, list) or not 5 <= len(points) <= 10000:
        raise RasterError("Provide 5–10,000 independent elevation checkpoints.")
    residuals, unavailable = [], 0
    with rasterio.open(path) as source:
        _check_dem(source)
        datum = vertical_datum(source)
        if declared_datum and datum and str(declared_datum).upper().replace("-", "").replace("_", "") != datum:
            raise RasterError("Checkpoint vertical datum does not match the DEM.")
        projection = Transformer.from_crs("EPSG:4326", source.crs, always_xy=True)
        for point in points:
            checkpoint(cancel)
            if not isinstance(point, dict):
                raise RasterError("Checkpoints must be objects.")
            lon = _finite(point.get("longitude"), "checkpoint longitude")
            lat = _finite(point.get("latitude"), "checkpoint latitude")
            height = _finite(point.get("elevation_m"), "checkpoint elevation")
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise RasterError("Checkpoint WGS84 coordinate out of range.")
            x, y = projection.transform(lon, lat)
            if not (math.isfinite(x) and math.isfinite(y)):
                unavailable += 1
                continue
            row, col = source.index(x, y)
            if not (0 <= row < source.height and 0 <= col < source.width):
                unavailable += 1
                continue
            reading = next(source.sample([(x, y)], indexes=1, masked=True))[0]
            if np.ma.is_masked(reading) or not np.isfinite(reading):
                unavailable += 1
                continue
            residuals.append(float(reading) - height)
    if len(residuals) < 5:
        raise RasterError("Fewer than five usable checkpoints overlap valid DEM cells.")
    errors = np.asarray(residuals, dtype=np.float64)
    absolute = np.abs(errors)
    median = float(np.median(errors))
    return {"sample_count": int(len(errors)), "unavailable_count": unavailable,
            "mean_error_m": float(errors.mean()),
            "rmse_m": float(np.sqrt(np.mean(errors**2))),
            "mae_m": float(absolute.mean()),
            "median_error_m": median,
            "nmad_m": float(1.4826 * np.median(np.abs(errors - median))),
            "absolute_error_p95_m": float(np.quantile(absolute, .95)),
            "minimum_error_m": float(errors.min()), "maximum_error_m": float(errors.max()),
            "datum_verified": bool(declared_datum and datum),
            "warning": "Checkpoint independence, land cover, measurement epoch and stated vertical datum require external verification; these descriptive errors are not certified accuracy."}
