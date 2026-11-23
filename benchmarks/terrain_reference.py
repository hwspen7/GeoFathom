"""Independent GDAL CLI benchmark for GeoFathom's numerical terrain derivatives.

No reference array is computed by GeoFathom. GDAL's standalone gdaldem
executable produces reference GeoTIFFs for all tests below. These tests
evaluate implementations, NOT the absolute accuracy of a field-survey DEM.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

from terrain.professional import derivatives, hillshade_illumination


def create_reference_dem(path: Path):
    # Use a non-flat analytic surface including slope, curvature and ripple.
    # Coordinates are in pixels; the transform supplies 10-meter spacing.
    y, x = np.indices((96, 104), dtype=np.float64)
    z = (470. + .19*x - .12*y + .0017*x*x + .0009*y*y
         + .27*np.sin(x/6.)*np.cos(y/9.)).astype("float32")
    with rasterio.open(path, "w", driver="GTiff", height=z.shape[0],
                       width=z.shape[1], count=1, dtype="float32",
                       crs="EPSG:32617", transform=from_origin(
                           500000, 4500000, 10, 10), nodata=-9999.) as ds:
        ds.write(z, 1)
    return z


def gdaldem(cli, name, source, target, alg=None):
    command = [cli, name, str(source), str(target), "-of", "GTiff"]
    if alg:
        command.extend(["-alg", alg])
    if name in {"slope", "hillshade"}:
        command.extend(["-s", "1.0"])
    response = subprocess.run(command, check=False, capture_output=True,
                              text=True, timeout=60)
    if response.returncode:
        raise RuntimeError(f"GDAL {name}/{alg} failed: {response.stderr[-1600:]}")
    with rasterio.open(target) as ds:
        result = ds.read(1, masked=True)
        return np.asarray(result.astype(np.float64).filled(np.nan), dtype=np.float64)


def metrics(reference, computed, tolerance, label):
    # Each sample is independently computed at the same physical grid center.
    ref = np.asarray(reference[1:-1, 1:-1], dtype=np.float64)
    actual = np.asarray(computed[1:-1, 1:-1], dtype=np.float64)
    good = np.isfinite(ref) & np.isfinite(actual)
    if good.sum() < 5000 or np.count_nonzero(np.isfinite(ref)^np.isfinite(actual)):
        raise AssertionError(f"{label}: missing or mismatched numeric pixels")
    if "aspect" in label:
        differences = np.abs((actual[good]-ref[good]+180.)%360.-180.)
    else:
        differences = np.abs(actual[good]-ref[good])
    worst = float(differences.max())
    root_mean_square = float(np.sqrt(np.mean(differences**2)))
    p95 = float(np.percentile(differences, 95))
    if not worst <= tolerance:
        raise AssertionError(
            f"{label}: maximum error {worst:.6g} > {tolerance:.6g}; "
            f"RMSE={root_mean_square:.6g}, n={good.sum()}")
    return {"name":label, "reference":"GDAL gdaldem CLI",
            "valid_compared":int(good.sum()), "max_absolute_error":worst,
            "rmse":root_mean_square, "p95_absolute_error":p95,
            "maximum_allowed":tolerance, "units":"degree" if "aspect" in label
            or "slope" in label else "m"}


def evaluate(source, workspace, cli):
    z = create_reference_dem(source)
    mask = np.ones(z.shape, dtype=bool)
    reports = []
    for method, gdal_name in (("horn", "Horn"),
                              ("zevenbergen_thorne", "ZevenbergenThorne")):
        actual = derivatives(z.astype(np.float64), mask, 10., 10.,
                             gradient_method=method)
        for kind, allowed in (("slope", .003), ("aspect", .025)):
            reference = gdaldem(cli, kind, source,
                                workspace/f"{kind}-{method}.tif", gdal_name)
            reports.append(metrics(reference, actual["slope_map" if kind=="slope"
                                    else "aspect_map"], allowed,
                                   f"{kind}-{method}"))
    # GDAL's Riley terrain ruggedness and 8-neighbor TPI are independent
    # algorithms and exercise the derivative code beyond slope/aspect.
    horn = derivatives(z.astype(np.float64), mask, 10., 10.)
    for kind, gdal_name, output, allowed in (
        ("TRI", "Riley", "tri", .001),
        ("TPI", None, "tpi", .001),
    ):
        reference = gdaldem(cli, kind, source,
                            workspace/f"{kind.lower()}.tif", gdal_name)
        reports.append(metrics(reference, horn[output], allowed, kind))
    # Hillshade's local Lambertian brightness is a separate reference
    # computation; GDAL's 8-bit convention may differ by up to 1 unit.
    reference = gdaldem(cli, "hillshade", source,
                        workspace/"hillshade.tif")
    actual = hillshade_illumination(horn["east"], horn["south"], 315., 45.)
    reports.append(metrics(reference, actual, 4., "hillshade-horn"))
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    cli = shutil.which("gdaldem")
    if cli is None:
        raise SystemExit("Independent GDAL benchmark requires gdaldem executable.")
    version = subprocess.check_output(["gdalinfo", "--version"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="geofathom-gdal-reference-") as tmp:
        folder = Path(tmp)
        results = evaluate(folder/"source.tif", folder, cli)
    output = {"schema_version":1, "reference_engine":version,
              "benchmark_type":"implementation_cross_check_on_synthetic_geotiff",
              "field_survey_certification":False,
              "reference_validation_scope":["slope_map","aspect_map","tri","tpi","hillshade"],
              "tests":results, "passed":len(results)==7}
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(output, indent=2, allow_nan=False)+"\n",
                    encoding="utf-8")
    print(json.dumps(output, indent=2))
    if args.strict and not output["passed"]:
        raise SystemExit("Missing independent scientific baseline comparisons")


if __name__=="__main__":
    main()
