"""Independent GIS reference comparisons (not self-referential unit tests).

PySheds D-infinity and GDAL gdal_viewshed use separately maintained
hydrological/visibility implementations. These controlled cases test numerical
implementation agreement, NOT the field accuracy of the underlying DEM.
"""
import shutil
import subprocess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from terrain.advanced import _visibility
from terrain.p1_science import dinfinity_accumulation


def test_dinfinity_cardinal_flow_agrees_with_independent_pysheds(tmp_path):
    pytest.importorskip("pysheds")
    from pysheds.grid import Grid

    z=np.tile(np.arange(32.,0.,-1.),(24,1)).astype("float32")
    src=tmp_path/"dinf-plane.tif"
    with rasterio.open(src,"w",driver="GTiff",height=24,width=32,count=1,
        crs="EPSG:32617",transform=from_origin(500000,4500000,10,10),
        dtype="float32",nodata=-9999) as ds:
        ds.write(z,1)
    independent=Grid.from_raster(str(src))
    dem=independent.read_raster(str(src))
    reference_flow=independent.flowdir(dem,routing="dinf")
    reference=np.asarray(independent.accumulation(reference_flow,routing="dinf"),
                         dtype=np.float64)
    actual,azimuth=dinfinity_accumulation(z,np.ones(z.shape,bool),10,10)
    # The cardinal analytic case is unambiguous across border conventions;
    # every interior row receives exactly the upstream cell count.
    expected=np.tile(np.arange(1.,33.),(24,1))
    np.testing.assert_allclose(reference[1:-1,1:-1],expected[1:-1,1:-1],rtol=0,atol=1e-4)
    np.testing.assert_allclose(actual[1:-1,1:-1],reference[1:-1,1:-1],rtol=0,atol=1e-4)
    np.testing.assert_allclose(azimuth[1:-1,:-1],0,atol=1e-12)


def test_ridge_shadow_matches_independent_gdal_viewshed(tmp_path):
    executable=shutil.which("gdal_viewshed")
    if executable is None:
        pytest.skip("Install GDAL CLI for independent viewshed comparison.")
    z=np.zeros((64,64),dtype=np.float32)
    z[:,32]=100
    aff=from_origin(500000,4500000,10,10)
    src=tmp_path/"ridge.tif";dest=tmp_path/"gdal-ridge.tif"
    with rasterio.open(src,"w",driver="GTiff",height=64,width=64,count=1,
        crs="EPSG:32617",transform=aff,dtype="float32",nodata=-9999) as ds:
        ds.write(z,1)
    x,y=aff*(8.5,32.5)
    command=[executable,"-ox",str(x),"-oy",str(y),"-oz","1.7",
             "-tz","0","-cc","0","-f","GTiff",str(src),str(dest)]
    result=subprocess.run(command,text=True,capture_output=True,timeout=45)
    assert result.returncode==0,result.stderr
    with rasterio.open(dest) as ds:
        gd=ds.read(1)
    actual,known=_visibility(z.astype(float),np.ones(z.shape,bool),(32,8),aff,1.7,0.,
                             consider_curvature=False)
    assert known.all()
    # Exclude the wall and near-horizon transition where GDAL's Wang2000
    # interpolation model and our cell-centre rays intentionally differ.
    near=np.s_[32,12:28]
    far=np.s_[32,40:60]
    assert np.all(actual[near]) and np.all(gd[near]==255)
    assert not np.any(actual[far]) and not np.any(gd[far]==255)
    assert np.mean((gd[near]==255)==actual[near])==1.
    assert np.mean((gd[far]==255)==actual[far])==1.
