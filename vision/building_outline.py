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


def fitted_outline(polygon, transform, *, maximum_window_pixels=1_048_576):
    """Bounded TLS edge fitting with explicit topology and raster support guards.

    Fit independent directions (no Manhattan assumption); intersect neighboring
    lines only near their original corners. No outward expansion is accepted,
    so adjacent vector footprints cannot newly overlap. Coordinates are estimates,
    not evidence of subpixel positional accuracy.
    """
    from shapely.geometry import Polygon
    affine = lambda t: [t.a, t.b, t.d, t.e, t.c, t.f]
    source = affine_transform(polygon, affine(~transform))
    fallback = lambda: guarded_outline(polygon, transform, maximum_window_pixels=maximum_window_pixels)
    if source.geom_type != "Polygon" or len(source.exterior.coords)>4096 or not source.is_valid:
        return fallback()
    left,top,right,bottom=source.bounds
    left,top=math.floor(left)-1,math.floor(top)-1
    right,bottom=math.ceil(right)+1,math.ceil(bottom)+1
    if (right-left)*(bottom-top)>maximum_window_pixels:
        return fallback()

    def ring_fit(ring):
        coords=np.asarray(ring.coords[:-1],np.float64)
        # Simplification only identifies edge segments; their lines are fitted
        # to the full original vertices. Retain short or ill-conditioned edges.
        from shapely.geometry import LinearRing
        guide=np.asarray(LinearRing(coords).simplify(.65,preserve_topology=True).coords[:-1])
        lookup={tuple(v):i for i,v in enumerate(coords)}
        if len(guide)<3 or len(guide)>=len(coords) or any(tuple(v) not in lookup for v in guide):
            return coords
        lines=[]
        for a,b in zip(guide,np.roll(guide,-1,axis=0)):
            start,end=lookup[tuple(a)],lookup[tuple(b)]
            idx=(np.arange((end-start)%len(coords)+1)+start)%len(coords)
            pts=coords[idx]
            center=pts.mean(axis=0)
            _,_,vh=np.linalg.svd(pts-center,full_matrices=False)
            direction=vh[0]
            if np.linalg.norm(b-a)<2:
                center=a;direction=(b-a)/max(np.linalg.norm(b-a),1e-12)
            lines.append((center,direction))
        result=[]
        for i,corner in enumerate(guide):
            a,u=lines[i-1]; b,v=lines[i]
            mat=np.column_stack((u,-v))
            if abs(np.linalg.det(mat))<.15:
                result.append(corner); continue
            point=a+u*np.linalg.solve(mat,b-a)[0]
            result.append(point if np.linalg.norm(point-corner)<=.75 else corner)
        return np.asarray(result)

    candidate=Polygon(ring_fit(source.exterior),[ring_fit(r) for r in source.interiors])
    if (candidate.is_empty or not candidate.is_valid or _topology(candidate)!=_topology(source)
            or candidate.equals(source) or candidate.difference(source).area>1e-8
            or source.area-candidate.area>min(2.,source.area*.005)
            or candidate.hausdorff_distance(source)>.75):
        return fallback()
    def cells(geometry):
        return rasterize([(mapping(geometry),1)],out_shape=(bottom-top,right-left),
                         transform=Affine.translation(left,top),dtype="uint8")
    if not np.array_equal(cells(candidate),cells(source)):
        return fallback()
    result=affine_transform(candidate,affine(transform))
    if not result.is_valid:
        return fallback()
    return result,{"outline_status":"fitted_pixel_support_preserved",
                   "outline_displacement_pixels":float(candidate.hausdorff_distance(source))}
