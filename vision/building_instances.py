"""Bounded, deterministic watershed separation on globally assembled masks."""
from contextlib import ExitStack
import math

import numpy as np
import rasterio
from rasterio.features import shapes, geometry_mask
from rasterio.transform import Affine
from rasterio.windows import Window
from scipy import ndimage as ndi
from shapely.geometry import shape, mapping
from shapely.affinity import affine_transform

from imagery.raster import RasterError
from .tiled import _preflight_mask, MAX_COMPONENTS


def separate_instances(foreground, probability, boundary=None, distance=None,
                       seed_distance=6, boundary_weight=1., max_instances=20000, *, adaptive=False):
    """Partition foreground pixels exactly; preserve background and courtyard holes.

    Predicted heads guide separation when present. A geometric distance field
    provides explicit fallback seeds; it does not establish building identity.
    """
    from skimage.morphology import h_maxima
    from skimage.segmentation import watershed
    foreground = np.asarray(foreground, bool)
    probability = np.asarray(probability, np.float32)
    if (foreground.ndim != 2 or probability.shape != foreground.shape
            or not np.isfinite(probability).all() or np.any((probability < 0) | (probability > 1))
            or type(seed_distance) is not int or not 1 <= seed_distance <= 64
            or not math.isfinite(boundary_weight) or not 0 <= boundary_weight <= 4):
        raise RasterError("Invalid building instance fields or seed parameters.")
    for field in (boundary, distance):
        if field is not None and (np.shape(field) != foreground.shape or not np.isfinite(field).all()):
            raise RasterError("Building auxiliary fields must match the mask and be finite.")
    if boundary is not None and np.any((boundary < 0) | (boundary > 1)):
        raise RasterError("Building boundaries require probabilities in [0,1].")
    if distance is not None and np.any((distance < -1) | (distance > 1)):
        raise RasterError("Building signed distance must lie in [-1,1].")
    if not foreground.any():
        return np.zeros(foreground.shape, np.int32)
    # Padding exposes the real background at component/window borders to EDT.
    radius = ndi.distance_transform_edt(np.pad(foreground, 1))[1:-1, 1:-1].astype(np.float32)
    geometric = radius / max(float(radius.max()), 1.)
    score = geometric if distance is None else .5 * geometric + .5 * np.maximum(distance, 0)
    score = np.where(foreground, score, 0).astype(np.float32)
    ridge = np.zeros_like(score) if boundary is None else np.asarray(boundary, np.float32)
    # h-maxima suppresses shallow numerical ripples, and each plateau receives one seed.
    peaks = h_maxima(score, .15) & foreground
    if adaptive:
        # Absolute prominence in source pixels preserves narrow attached roofs
        # whose normalized peak is suppressed by a much wider neighbor.
        peaks |= h_maxima(radius, .8) & foreground
    peak_labels, count = ndi.label(peaks)
    candidates = []
    for index, window in enumerate(ndi.find_objects(peak_labels), 1):
        if window is None:
            continue
        positions = np.argwhere(peak_labels[window] == index)
        values = score[window][peak_labels[window] == index]
        pos = positions[int(np.argmax(values))] + np.array([window[0].start, window[1].start])
        candidates.append((float(score[tuple(pos)]), int(pos[0]), int(pos[1])))
    # Declared boundary heads can separate equal-height touching roofs that share an EDT plateau.
    if boundary is not None:
        interiors, interior_count = ndi.label(foreground & (ridge < .5))
        component_count = ndi.label(foreground)[1]
        if interior_count > component_count:
            # Strong boundary-separated interiors take precedence over a shared geometric peak.
            candidates = []
        for index, window in enumerate(ndi.find_objects(interiors), 1):
            if window is None:
                continue
            positions = np.argwhere(interiors[window] == index)
            local = interiors[window] == index
            interior_distance = ndi.distance_transform_edt(np.pad(local, 1))[1:-1, 1:-1]
            values = (interior_distance + .1*score[window])[local]
            if len(values) < 3:
                continue
            pos = positions[int(np.argmax(values))] + np.array([window[0].start, window[1].start])
            if interior_count > component_count:
                candidates.append((float(score[tuple(pos)]), int(pos[0]), int(pos[1])))
    markers = np.zeros(foreground.shape, np.int32)
    from .building_seeds import select_seeds
    try:
        selected = select_seeds(candidates, radius, seed_distance, adaptive=adaptive, limit=max_instances)
    except ValueError as error:
        raise RasterError(str(error)) from error
    for index, (y, x) in enumerate(selected, 1):
        markers[y, x] = index
    # Every connected component gets a seed, including small/thin low-confidence regions.
    components, _ = ndi.label(foreground)
    for index, window in enumerate(ndi.find_objects(components), 1):
        if window is None:
            continue
        mask = components[window] == index
        if not np.any(markers[window][mask]):
            positions = np.argwhere(mask)
            pos = positions[int(np.argmax(score[window][mask]))]
            y, x = int(pos[0]+window[0].start), int(pos[1]+window[1].start)
            selected.append((y, x))
            if len(selected) > max_instances:
                raise RasterError("Too many connected building candidates.")
            markers[y, x] = len(selected)
    # Low mask probability is weak ridge evidence, never a mask erasure.
    cost = -score + boundary_weight*ridge
    if adaptive:
        cost = cost + .2*(1-probability)
    result = watershed(cost, markers, mask=foreground,
                       connectivity=1, watershed_line=False).astype(np.int32)
    if not np.array_equal(result > 0, foreground):
        raise RasterError("Instance separation changed the foreground support.")
    return result

    
def separate_components(foreground, probability, boundary=None, distance=None, *, seed_distance=6,
                        boundary_weight=1., max_instances=20000, adaptive=False, graph=False):
    """Use component-local normalization, as in the production disk path."""
    foreground = np.asarray(foreground, bool)
    if foreground.ndim != 2 or any(np.shape(f) != foreground.shape for f in
                                  (probability, boundary, distance) if f is not None):
        raise RasterError("Component fields must share the foreground grid.")
    components, _ = ndi.label(foreground)
    output = np.zeros(foreground.shape, np.int32)
    total = 0
    for index, window in enumerate(ndi.find_objects(components), 1):
        if window is None:
            continue
        local = components[window] == index
        fields = [np.where(local, f[window], 0) if f is not None else None
                  for f in (probability, boundary, distance)]
        if graph:
            from .building_graph import graph_partition
            labels = graph_partition(local, *fields, seed_distance=seed_distance,
                                     boundary_weight=boundary_weight, max_instances=max_instances-total)
        else:
            labels = separate_instances(local, *fields, seed_distance=seed_distance,
                                        boundary_weight=boundary_weight, max_instances=max_instances-total, adaptive=adaptive)
        output[window][local] = labels[local] + total
        total += int(labels.max())
    return output


class InstanceClasses:
    """A lazy class-name mapping for positive instance IDs during polygonization."""
    def __contains__(self, value):
        return value > 0

    def __getitem__(self, value):
        return "building"


def instance_raster(mask_path, probability_path, destination, *, boundary_path=None,
                    distance_path=None, seed_distance=6, boundary_weight=1., memory_mb=64,
                    progress=None, adaptive=False, graph=False):
    """Separate one complete connected component at a time, across all tile seams."""
    total = 0
    with ExitStack() as stack:
        mask = stack.enter_context(rasterio.open(mask_path))
        probability = stack.enter_context(rasterio.open(probability_path))
        boundary = stack.enter_context(rasterio.open(boundary_path)) if boundary_path else None
        distance = stack.enter_context(rasterio.open(distance_path)) if distance_path else None
        for field in (probability, boundary, distance):
            if field is not None and (field.crs, field.transform, field.shape) != (mask.crs, mask.transform, mask.shape):
                raise RasterError("Building instance rasters must share one source grid.")
        _preflight_mask(mask, progress)
        profile = mask.profile.copy()
        profile.update(dtype="int32", nodata=0)
        output = stack.enter_context(rasterio.open(destination, "w+", **profile))
        scanned = 0
        # GDAL polygonization joins connected regions before reading their local fields.
        for geometry, category in shapes(rasterio.band(mask, 1), transform=Affine.identity(), connectivity=4):
            if int(category) != 1:
                continue
            scanned += 1
            if scanned > MAX_COMPONENTS:
                raise RasterError("Too many connected regions for instance extraction.")
            # GDAL Band polygonization returns source-CRS coordinates even with an
            # identity transform argument. Convert explicitly back to the pixel grid.
            inverse = ~mask.transform
            polygon = affine_transform(shape(geometry), [inverse.a, inverse.b, inverse.d,
                inverse.e, inverse.c, inverse.f])
            geometry = mapping(polygon)
            left, top, right, bottom = [int(round(value)) for value in polygon.bounds]
            pixels = (right-left) * (bottom-top)
            # Includes EDT, watershed queues, candidate coordinates and geometric masks.
            if pixels * (320 if graph else 160) > memory_mb * 1024**2:
                raise RasterError("A connected region exceeds instance memory; increase allowance or reduce AOI.")
            window = Window(left, top, right-left, bottom-top)
            foreground = geometry_mask([geometry], (bottom-top, right-left),
                Affine.translation(left, top), invert=True)
            fields = [s.read(1, window=window) if s is not None else None for s in (probability, boundary, distance)]
            # Auxiliary nodata lies outside the component and is excluded explicitly.
            fields = [np.where(foreground, field, 0) if field is not None else None for field in fields]
            if graph:
                from .building_graph import graph_partition
                labels = graph_partition(foreground, *fields, seed_distance=seed_distance, boundary_weight=boundary_weight)
            else:
                labels = separate_instances(foreground, fields[0], fields[1], fields[2], seed_distance, boundary_weight,
                                            adaptive=adaptive)
            count = int(labels.max())
            if total + count > MAX_COMPONENTS:
                raise RasterError("Too many building instances; reduce the study area.")
            # Component bounding boxes can overlap (courtyards with detached inner buildings).
            # Preserve previously written, disjoint foreground instead of overwriting with zeros.
            labels = np.where(labels > 0, labels + total, 0).astype(np.int32)
            # A separate read handle would miss buffered writes. Rasterio's w+ supports read/modify/write.
            current = output.read(1, window=window)
            output.write(np.where(foreground, labels, current).astype(np.int32), 1, window=window)
            total += count
            if progress is not None:
                progress(.84)
    return {"instances": total, "connected_components": scanned,
            "adaptive": adaptive,
            "method": ("graph_" if graph else "adaptive_" if adaptive else "") + (
                "boundary_distance_watershed" if boundary_path or distance_path else "geometric_distance_watershed")}
