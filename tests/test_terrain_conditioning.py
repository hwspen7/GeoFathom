"""Numerical regression cases for conditioned drainage and corrected viewsheds."""
import numpy as np
import pytest
from rasterio.transform import from_origin

from terrain.hydrology import condition_dem
from terrain.professional import d8_flow
from terrain.advanced import _visibility
from imagery.raster import RasterError


def test_priority_flood_removes_interior_sink_and_preserves_source():
    original=np.full((7,7),10.,dtype=np.float64)
    original[1:-1,1:-1]=2.
    original[3,3]=0.
    untouched=original.copy()
    valid=np.ones_like(original,dtype=bool)
    conditioned,metrics=condition_dem(original,valid)
    np.testing.assert_array_equal(original,untouched)
    assert metrics["conditioned_cells"]==25
    assert metrics["maximum_fill_depth_m"]>=10.
    assert metrics["outlet_cells"]==24
    receivers,_,accum=d8_flow(conditioned,valid,10.,10.)
    # An interior basin must drain to the edge, never remain an artificial sink.
    for r in range(1,6):
        for c in range(1,6):
            assert receivers[r,c]>=0
    center=(3,3)
    for _ in range(49):
        r,c=center
        dest=int(receivers[r,c])
        if r in (0,6) or c in (0,6):
            break
        assert dest>=0
        center=divmod(dest,7)
    assert center[0] in (0,6) or center[1] in (0,6)
    assert np.isfinite(accum[valid]).all()


def test_nodata_not_filled_or_manufactured():
    original=np.full((5,5),3.,dtype=np.float64)
    valid=np.ones((5,5),dtype=bool)
    valid[2,2]=False
    original[2,2]=np.nan
    conditioned,metrics=condition_dem(original,valid)
    assert np.isnan(conditioned[2,2])
    assert metrics["outlet_cells"]>16
    assert np.all(np.isfinite(conditioned[valid]))


def test_viewshed_curvature_hides_far_flat_surface():
    z=np.zeros((1,900),dtype=np.float64)
    valid=np.ones_like(z,dtype=bool)
    affine=from_origin(0,9000,10,10)
    planar,known=_visibility(z,valid,(0,0),affine,1.7,0.)
    curved,known_curved=_visibility(
        z,valid,(0,0),affine,1.7,0.,
        consider_curvature=True,refraction_coeff=0.13)
    assert known.all() and known_curved.all()
    assert planar[0,-1]
    assert curved[0,10]
    assert not curved[0,-1]


def test_viewshed_refraction_input_validation():
    z=np.zeros((5,5),dtype=float)
    with pytest.raises(RasterError,match="refraction"):
        _visibility(z,np.ones_like(z,bool),(2,2),from_origin(0,50,10,10),
                    1.7,0.,consider_curvature=True,refraction_coeff=1.0)


def test_flat_terrain_drains_without_artificial_fill_volume():
    # A flat DEM needs numerical routing gradients, not fabricated physical
    # fill material. No source pixel may be modified by the algorithm.
    original=np.full((9,9),100.0,dtype=np.float64)
    mask=np.ones_like(original,dtype=bool)
    working,metrics=condition_dem(original,mask)
    assert metrics['conditioned_cells']==0
    assert metrics['maximum_fill_depth_m']==0
    assert metrics['total_fill_depth_m']==0
    assert metrics['flat_routing_cells']>0
    np.testing.assert_array_equal(original,np.full_like(original,100.0))
    downstream,_,_=d8_flow(working,mask,10,10)
    assert downstream[4,4]>=0


def test_nested_sink_metrics_exclude_flat_routing_epsilon():
    values=np.full((7,7),15.,dtype=np.float64)
    values[1:-1,1:-1]=5.
    values[3,3]=0.
    routed,metrics=condition_dem(values,np.ones_like(values,bool))
    assert metrics['conditioned_cells']==25
    assert metrics['maximum_fill_depth_m']==pytest.approx(15.)
    assert metrics['total_fill_depth_m']==pytest.approx(25*10+5)
    assert metrics['flat_routing_cells']>0
    assert routed[3,3]>=15.
