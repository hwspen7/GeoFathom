"""Conservative building vector simplification on the original raster grid."""
import math

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.affinity import affine_transform
from shapely.geometry import mapping


def _topology(geometry):
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    return len(polygons), sorted(len(poly.interiors) for poly in polygons)


def guarded_outline(polygon, transform, *, maximum_window_pixels=1_048_576):
    """Allow only topology-preserving, inward edits with identical pixel support.

    Work in pixel coordinates, including rotated/sheared source grids. A failed
    check returns the exact unsimplified footprint rather than forcing a shape.
    """
    inverse = ~transform
    affine = lambda t: [t.a, t.b, t.d, t.e, t.c, t.f]
    source = affine_transform(polygon, affine(inverse))
    candidate = source.simplify(.35, preserve_topology=True)
    status = "native_grid_retained"
    if candidate.equals_exact(source, 0.):
        return polygon, {"outline_status": status}
    if (candidate.is_empty or not candidate.is_valid
            or candidate.geom_type != source.geom_type
            or _topology(candidate) != _topology(source)
            or candidate.difference(source).area > 1e-8
            or source.area-candidate.area > min(.25, source.area*.005)):
        return polygon, {"outline_status": status}
    left, top, right, bottom = source.bounds
    left, top = math.floor(left)-1, math.floor(top)-1
    right, bottom = math.ceil(right)+1, math.ceil(bottom)+1
    width, height = right-left, bottom-top
    if width*height > maximum_window_pixels:
        return polygon, {"outline_status": "native_grid_retained_window_budget"}
    def cells(geometry):
        return rasterize([(mapping(geometry), 1)], out_shape=(height, width),
                         transform=Affine.translation(left, top), dtype="uint8")
    if not np.array_equal(cells(source), cells(candidate)):
        return polygon, {"outline_status": status}
    refined = affine_transform(candidate, affine(transform))
    if not refined.is_valid:
        return polygon, {"outline_status": status}
    return refined, {"outline_status": "guarded_pixel_support_preserved"}
