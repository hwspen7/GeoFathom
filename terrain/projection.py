"""Projection-scale audit for physically meaningful horizontal distances.

Coordinate reference systems may have meter axes and still distort ground
lengths. Local terrain derivatives treat projected grid spacing as meters on
the ground, so large distortion must be rejected, never silently ignored.

This measures local meridional and parallel map scale at the center and
four bounds corners. It does not assess DEM vertical uncertainty, and
projection distortion below the gate is not a survey-accuracy certificate.
"""
import math
from pyproj import Proj, Transformer

from imagery.raster import RasterError


def grid_scale_error_percent(dataset, maximum_percent=2.):
    """Maximum sampled departure of projected length from ground length."""
    try:
        b=dataset.bounds
        mid_x=(b.left+b.right)/2
        mid_y=(b.bottom+b.top)/2
        points=((mid_x,mid_y),(b.left,b.top),(b.right,b.top),
                (b.left,b.bottom),(b.right,b.bottom))
        inverse=Transformer.from_crs(dataset.crs,"EPSG:4326",always_xy=True)
        projection=Proj(dataset.crs.to_wkt())
        errors=[]
        for xx,yy in points:
            lon,lat=inverse.transform(xx,yy)
            if not(-180<=lon<=180 and -90<=lat<=90):
                raise ValueError("DEM projected bounds are outside the geographic domain")
            factors=projection.get_factors(lon,lat)
            error=max(abs(float(factors.meridional_scale)-1),
                      abs(float(factors.parallel_scale)-1))
            if not math.isfinite(error):
                raise ValueError("Projection scale is not finite")
            errors.append(100*error)
    except RasterError:
        raise
    except Exception as exc:
        raise RasterError(
            "Unable to validate DEM projected ground-distance scale; "
            "reproject to a suitable local metric CRS.") from exc
    worst=max(errors)
    if worst>maximum_percent:
        raise RasterError(
            f"DEM projection scale distortion reaches {worst:.2f}% "
            f"(maximum {maximum_percent:g}%). Web Mercator and other "
            "high-distortion CRSs must be reprojected into a suitable "
            "local UTM or low-distortion metric CRS before quantitative "
            "terrain analysis.")
    return float(worst)
