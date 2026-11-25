"""Schema and numerical acceptance tests for configurable Terrain neighborhoods."""
import numpy as np
import pytest
from terrain.catalog import GROUPS, CORE_OPERATIONS, ADVANCED_OPERATIONS, terrain_catalog
from terrain.multiscale import multiscale_terrain
from imagery.raster import RasterError


def test_catalog_has_exactly_28_unique_operations_and_explicit_uncertainty():
    items=terrain_catalog()["operations"]
    assert len(items)==len(CORE_OPERATIONS)==28
    assert len(ADVANCED_OPERATIONS)==26
    assert {x["id"] for x in items}==CORE_OPERATIONS
    assert set(GROUPS)=={"Surface","Hydrology","Visibility","Engineering","3D"}
    assert all(x["validation"]=="requires_independent_reference" for x in items)


def test_multiscale_plane_has_zero_tpi_and_radius_dependent_tri():
    grid=np.tile(np.arange(13,dtype=float),(13,1))
    good=np.ones_like(grid,bool)
    tpi=multiscale_terrain(grid,good,3,"tpi")
    tri1=multiscale_terrain(grid,good,1,"tri")
    tri3=multiscale_terrain(grid,good,3,"tri")
    assert tpi[6,6]==pytest.approx(0)
    assert tri3[6,6]>tri1[6,6]>0
    assert np.isnan(tpi[0]).all()


def test_multiscale_validity_does_not_cross_nodata_or_invalid_radius():
    grid=np.ones((11,11),float)
    mask=np.ones_like(grid,bool)
    mask[5,5]=False
    output=multiscale_terrain(grid,mask,2,"tpi")
    assert np.isnan(output[3:8,3:8]).all()
    assert np.isfinite(output[2,2])
    with pytest.raises(RasterError,match="radius"):
        multiscale_terrain(grid,mask,5,"tpi")
    with pytest.raises(RasterError,match="small"):
        multiscale_terrain(grid[:3,:3],mask[:3,:3],2,"tpi")
