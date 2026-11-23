"""P0 scientific invariants with independently constructed reference solutions.

These fixtures do not use the terrain engine itself to calculate expected
answers. They check conservation, analytic surfaces, topology and ray geometry.
They are evidence of numerical implementation quality, not survey accuracy.
"""
from collections import defaultdict
from functools import lru_cache
from math import hypot, radians, sqrt

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box, shape

from imagery.raster import RasterError
from terrain.advanced import _contours, _visibility, _watershed
from terrain.hydrology import condition_dem
from terrain.multiflow import mfd_accumulation
from terrain.professional import (
    d8_directions, d8_flow, derivatives, least_cost, surface,
)
from terrain.multiscale import multiscale_terrain


NEIGHBORS = [(-1,0),(-1,1),(0,1),(1,1),(1,0),(1,-1),(0,-1),(-1,-1)]
DIRECTION_CODES = [64,128,1,2,4,8,16,32]


def reference_mfd(elevation, valid, dx, dy, power):
    """Tiny reference: recursive upstream sum, not the engine's forward pass."""
    height,width=elevation.shape
    incoming=defaultdict(list)
    for r in range(height):
        for c in range(width):
            if not valid[r,c]:
                continue
            options=[]
            for dr,dc in NEIGHBORS:
                row,col=r+dr,c+dc
                if not(0<=row<height and 0<=col<width and valid[row,col]):
                    continue
                if dr and dc and not(valid[r,col] and valid[row,c]):
                    continue
                gradient=(elevation[r,c]-elevation[row,col])/hypot(dr*dy,dc*dx)
                if gradient>0:
                    options.append(((row,col),gradient))
            if options:
                scale=max(gradient for _,gradient in options)
                weights=[(gradient/scale)**power for _,gradient in options]
                total=sum(weights)
                for (receiver,_),weight in zip(options,weights):
                    incoming[receiver].append(((r,c),weight/total))
    @lru_cache(None)
    def accumulation(node):
        return 1.+sum(accumulation(source)*weight for source,weight in incoming[node])
    values=np.full(elevation.shape,np.nan)
    for r,c in np.argwhere(valid):
        values[r,c]=accumulation((int(r),int(c)))
    return values


@pytest.mark.parametrize("exponent",[.5,1.1,2.5,8.])
def test_mfd_against_independent_recursive_fractional_graph(exponent):
    row,col=np.indices((6,7))
    z=100.-1.3*row-1.8*col+.11*row*col
    valid=np.ones(z.shape,bool)
    valid[2,4]=False
    reference=reference_mfd(z,valid,10.,17.,exponent)
    actual=mfd_accumulation(z,valid,10.,17.,exponent=exponent)
    np.testing.assert_allclose(actual,reference,atol=1e-11,rtol=1e-11,
                               equal_nan=True)
    # Every input cell equivalent must arrive at exactly one local outlet.
    downstream, _=d8_directions(z,valid,10.,17.)
    assert np.isfinite(actual[valid]).all()
    assert np.nanmax(actual)<=valid.sum()+1e-10
    assert (downstream[~valid]==-1).all()


def test_d8_upstream_mass_conserved_at_local_outlets():
    y,x=np.indices((15,17))
    z=200.-1.31*y-1.73*x+.005*(x-6)**2
    valid=np.ones(z.shape,bool)
    valid[3,6]=valid[4,6]=False
    dst,directions,accum=d8_flow(z,valid,15.,20.)
    outlets=(dst==-1)&valid
    assert outlets.any()
    assert np.nansum(accum[outlets])==pytest.approx(int(valid.sum()))
    for r,c in np.argwhere(valid):
        receiver=int(dst[r,c])
        if receiver>=0:
            rr,cc=divmod(receiver,z.shape[1])
            assert z[rr,cc]<z[r,c]
            assert accum[rr,cc]>=accum[r,c]+1
            assert directions[r,c] in DIRECTION_CODES
    # Masked pixels never become graph vertices or counted accumulation.
    assert np.isnan(accum[~valid]).all()


@pytest.mark.parametrize("radius",[1,2,3,4])
def test_multiscale_ruggedness_and_position_match_scalar_reference(radius):
    y,x=np.indices((17,17))
    z=(100+.23*x+.04*y+.01*x*y).astype(float)
    valid=np.ones_like(z,bool)
    valid[3,3]=False
    for op in ("tri","tpi"):
        observed=multiscale_terrain(z,valid,radius,op,block=5)
        n=2*radius+1
        for row,col in ((8,8),(10,11),(3,3)):
            window=z[row-radius:row+radius+1,col-radius:col+radius+1]
            ok=valid[row-radius:row+radius+1,col-radius:col+radius+1].all()
            if not ok:
                assert np.isnan(observed[row,col])
                continue
            center=z[row,col]
            if op=="tri":
                ref=sqrt(float(np.sum((window-center)**2)))
            else:
                ref=center-(float(window.sum())-center)/(n*n-1)
            assert observed[row,col]==pytest.approx(ref,abs=1e-10)


@pytest.mark.parametrize("gradient",["horn","zevenbergen_thorne"])
def test_quadratic_differentials_match_analytic_hessian(gradient):
    y,x=np.indices((17,17),dtype=float)
    X=x*12.; Y=y*15.
    # z_xx=.0008, z_yy=.0014, z_xy=0 exactly at cell centers.
    heights=100.+.04*X+.09*Y+.0004*X*X+.0007*Y*Y
    deriv=derivatives(heights,np.ones_like(heights,bool),12.,15.,gradient)
    r,c=8,8
    east=.04+.0008*X[r,c]
    south=.09+.0014*Y[r,c]
    squared=east**2+south**2
    expected_slope=np.degrees(np.arctan(np.sqrt(squared)))
    expected_plan=(south**2*.0008+east**2*.0014)/squared**1.5
    expected_profile=(east**2*.0008+south**2*.0014)/(squared*(1+squared)**1.5)
    assert deriv["slope_map"][r,c]==pytest.approx(expected_slope,abs=1e-9)
    assert deriv["curvature"][r,c]==pytest.approx(.0022,abs=1e-10)
    assert deriv["plan_curvature"][r,c]==pytest.approx(expected_plan,rel=1e-7)
    assert deriv["profile_curvature"][r,c]==pytest.approx(expected_profile,rel=1e-7)


def test_priority_flood_preserves_true_height_and_reports_only_physical_fill():
    height=np.full((9,9),10.,dtype=float)
    height[1:8,1:8]=4.
    height[4,4]=1.
    valid=np.ones_like(height,bool)
    original=height.copy()
    filled,metrics=condition_dem(height,valid)
    np.testing.assert_array_equal(original,height)
    assert np.all(filled>=height)
    assert metrics["total_fill_depth_m"]==pytest.approx(49*6+3)
    assert metrics["conditioned_cells"]==49
    _,_,flow=d8_flow(filled,valid,10.,10.)
    assert np.isfinite(flow).all()
    assert np.nansum(flow[0,:])>=9


def reference_line_of_sight(grid,valid,origin,target,observer_height,target_height):
    """Independent scalar nearest-center ray with no curvature or refraction."""
    r0,c0=origin
    r,c=target
    steps=max(abs(r-r0),abs(c-c0))
    if not steps:
        return True,True
    eye=grid[r0,c0]+observer_height
    endpoint=grid[r,c]+target_height
    all_known=True
    unobstructed=True
    for index in range(1,steps):
        fraction=index/steps
        rr=round(r0+(r-r0)*fraction)
        cc=round(c0+(c-c0)*fraction)
        if not valid[rr,cc]:
            all_known=False
            continue
        line=eye+(endpoint-eye)*fraction
        if grid[rr,cc]>line+1e-8:
            unobstructed=False
    # Missing intermediate elevations are unknown even if another cell blocks
    # the ray; no arbitrary order of blockers may conceal missing evidence.
    return all_known and unobstructed,all_known


def test_viewshed_agrees_with_independent_scalar_ray_visibility():
    y,x=np.indices((9,11))
    heights=np.where((x==5)&(y>=2)&(y<=7),23.,0.).astype(float)
    mask=np.ones_like(heights,bool)
    mask[2,7]=False
    heights[~mask]=np.nan
    observer=(4,1)
    seen,known=_visibility(heights,mask,observer,from_origin(0,90,10,10),
                           1.7,0.,consider_curvature=False)
    for point in map(tuple,np.argwhere(mask)):
        expect_visible,expect_known=reference_line_of_sight(
            heights,mask,observer,point,1.7,0.)
        assert known[point]==expect_known
        assert seen[point]==expect_visible


def test_flat_dijkstra_route_has_exact_theoretical_distance():
    z=np.zeros((9,9))
    valid=np.ones_like(z,bool)
    expected=8*hypot(8.,11.)
    for model in ("distance","surface","gentle"):
        path,cost=least_cost(z,valid,(0,0),(8,8),8.,11.,30.,
                             route_model=model)
        assert path[0]==(0,0) and path[-1]==(8,8)
        assert len(path)==9
        assert cost==pytest.approx(expected,rel=1e-13)


def test_planar_contours_have_exact_interpolated_horizontal_coordinates():
    z=np.tile(np.arange(9,dtype=float)*10,(9,1))
    affine=from_origin(500000,4500000,10,10)
    boundary=box(*raster_bounds(z.shape,affine))
    output=_contours(z,np.ones_like(z,bool),affine,"EPSG:32617",
                     boundary,25.)
    assert {f["properties"]["elevation_m"] for f in output}=={25.,50.,75.}
    to_utm=Transformer.from_crs("EPSG:4326","EPSG:32617",always_xy=True)
    for feature in output:
        contour=shape(feature["geometry"])
        expected_x=500005+feature["properties"]["elevation_m"]
        for line in (contour.geoms if contour.geom_type=="MultiLineString" else [contour]):
            for lon,lat in line.coords:
                x,_=to_utm.transform(lon,lat)
                assert x==pytest.approx(expected_x,abs=1e-5)


def raster_bounds(shape_,affine):
    height,width=shape_
    left,top=affine*(0,0)
    right,bottom=affine*(width,height)
    return left,bottom,right,top
