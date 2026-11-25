"""Score the deployed building mask and retained polygons against supplied labels."""
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from rasterio.windows import Window
from shapely.geometry import shape

from imagery.raster import RasterError
from imagery.store import file_sha256
from .quality import confusion_matrix, metrics_from_matrix


def object_metrics(predicted, truth, iou_threshold=.5):
    """Maximum-cardinality, one-to-one matching at a fixed polygon IoU threshold."""
    from scipy.optimize import linear_sum_assignment
    if not 0 < iou_threshold <= 1:
        raise ValueError("Invalid object IoU threshold.")
    if len(predicted) > 20000 or len(truth) > 20000:
        raise RasterError("Object evaluation exceeds the bounded matching budget.")
    matches = []
    if predicted and truth:
        # Use sparse spatial candidates for dense scenes instead of allocating N×M matrices.
        if len(predicted)*len(truth) > 1_000_000:
            from shapely.strtree import STRtree
            from scipy.sparse import csr_matrix
            from scipy.sparse.csgraph import maximum_bipartite_matching
            tree = STRtree(truth)
            edges, scores = [], {}
            for i, first in enumerate(predicted):
                for j in tree.query(first, predicate="intersects"):
                    second = truth[int(j)]
                    union = first.union(second).area
                    overlap = first.intersection(second).area/union if union else 0.
                    if overlap >= iou_threshold:
                        edges.append((i, int(j)))
                        scores[(i, int(j))] = overlap
                    if len(edges) > 1_000_000:
                        raise RasterError("Object overlap graph exceeds the sparse matching budget.")
            if edges:
                rows, cols = zip(*edges)
                graph = csr_matrix((np.ones(len(edges), np.uint8), (rows, cols)), shape=(len(predicted), len(truth)))
                assignment = maximum_bipartite_matching(graph, perm_type="column")
                matches = [scores[(i, int(j))] for i, j in enumerate(assignment) if j >= 0]
            tp = len(matches)
            fp, fn = len(predicted)-tp, len(truth)-tp
            return {"iou_threshold": iou_threshold, "true_positive": tp, "false_positive": fp, "false_negative": fn,
                "precision": tp/(tp+fp) if tp+fp else 0., "recall": tp/(tp+fn) if tp+fn else 0.,
                "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
                "mean_matched_iou": float(np.mean(matches)) if matches else None,
                "matching": "sparse maximum cardinality; matched-IoU ties are not optimized"}
        ious = np.zeros((len(predicted), len(truth)), np.float64)
        for i, first in enumerate(predicted):
            for j, second in enumerate(truth):
                if first.intersects(second):
                    union = first.union(second).area
                    ious[i, j] = first.intersection(second).area / union if union else 0.
        # A cardinality bonus dominates any IoU tie-break across all assignments.
        eligible = ious >= iou_threshold
        score = eligible * (min(ious.shape) + 1 + ious)
        rows, cols = linear_sum_assignment(score, maximize=True)
        matches = [float(ious[i, j]) for i, j in zip(rows, cols) if eligible[i, j]]
    tp = len(matches)
    fp, fn = len(predicted) - tp, len(truth) - tp
    return {"iou_threshold": iou_threshold, "true_positive": tp,
        "false_positive": fp, "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else 0.,
        "recall": tp / (tp + fn) if tp + fn else 0.,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.,
        "mean_matched_iou": float(np.mean(matches)) if matches else None,
        "empty_scene_policy": "Undefined precision/recall/F1 reported as zero; counts retained."}


def evaluate_outputs(output_dir, labels, reference_geojson=None):
    """Use every jointly valid labeled pixel, including false-positive background.

    Labels must be explicit 0=background, 1=building; nodata is excluded using
    the label raster mask. No confidence rejection or accuracy gate is applied.
    """
    root = Path(output_dir)
    matrix = np.zeros((2, 2), np.int64)
    squared_error = 0.
    with rasterio.open(root / "mask.tif") as mask, rasterio.open(labels) as truth, \
            rasterio.open(root / "probability.tif") as probability:
        if (mask.crs, mask.transform, mask.shape) != (probability.crs, probability.transform, probability.shape):
            raise RasterError("Building mask and probabilities have different grids.")
        with WarpedVRT(truth, crs=mask.crs, transform=mask.transform,
                       width=mask.width, height=mask.height,
                       nodata=255,
                       resampling=Resampling.nearest) as aligned:
            for y in range(0, mask.height, 256):
                for x in range(0, mask.width, 256):
                    window = Window(x, y, min(256, mask.width-x), min(256, mask.height-y))
                    actual = mask.read(1, window=window, masked=True)
                    reference = aligned.read(1, window=window, masked=True)
                    scores = probability.read(1, window=window, masked=True)
                    valid = (~np.ma.getmaskarray(actual) & ~np.ma.getmaskarray(reference)
                             & ~np.ma.getmaskarray(scores))
                    matrix += confusion_matrix(reference.data, actual.data, 2, valid)
                    squared_error += float(np.sum((scores.data[valid].astype(np.float64)-reference.data[valid])**2))
        result = metrics_from_matrix(matrix, ["background", "building"])
        if not result["valid_pixels"]:
            raise RasterError("No jointly valid building evaluation pixels.")
        result["brier_score"] = squared_error / result["valid_pixels"]
        result["labels_sha256"] = file_sha256(Path(labels))
        result["prediction_sha256"] = file_sha256(root / "mask.tif")
        result["probability_sha256"] = file_sha256(root / "probability.tif")
        if reference_geojson is not None:
            collection = json.loads((root / "footprints.geojson").read_text(encoding="utf-8"))
            labels_geojson = json.loads(Path(reference_geojson).read_text(encoding="utf-8"))
            def polygons(features):
                items = []
                for feature in features:
                    geom = shape(transform_geom("EPSG:4326", str(mask.crs), feature["geometry"]))
                    if geom.is_empty or not geom.is_valid or geom.geom_type not in ("Polygon", "MultiPolygon"):
                        raise RasterError("Object reference contains an invalid polygon.")
                    items.append(geom)
                return items
            result["objects"] = object_metrics(polygons(collection["features"]), polygons(labels_geojson["features"]))
            result["reference_geojson_sha256"] = file_sha256(Path(reference_geojson))
            result["object_output_truncated"] = collection["truncated"]
    return result
