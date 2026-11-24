"""Numerical and whole-pipeline fixtures for MFD flow and Strahler stream order."""
import base64
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from imagery.raster import RasterError
from terrain.multiflow import mfd_accumulation,strahler_orders
from terrain.advanced import run_terrain
from terrain.cancellation import TerrainCancelled
from threading import Event


def test_mfd_single_downhill_path_is_exact_cell_count():
    z=np.array([[5.,4.,3.,2.,1.]])
    result=mfd_accumulation(z,np.ones_like(z,bool),10,20)
    np.testing.assert_allclose(result,[[1.,2.,3.,4.,5.]],rtol=0,atol=1e-12)


def test_mfd_divides_flow_and_conserves_all_cell_contributions():
    z=np.array([[5.,4.,3.],[4.,3.,2.],[3.,2.,1.]])
    valid=np.ones(z.shape,dtype=bool)
    result=mfd_accumulation(z,valid,10,10)
    # Bottom-right is the only local outlet; it receives all 9 cells.
    assert result[2,2]==pytest.approx(9,abs=1e-10)
    assert 1 < result[0,1] < 3
    assert np.isfinite(result).all()
    assert result[0,0]==1


def test_mfd_never_invents_a_diagonal_channel_through_nodata():
    z=np.array([[5.,np.nan],[np.nan,1.]])
    valid=np.array([[True,False],[False,True]])
    result=mfd_accumulation(z,valid,10,10)
    assert result[0,0]==1 and result[1,1]==1
    assert np.isnan(result[0,1]) and np.isnan(result[1,0])


def test_mfd_cancels_and_rejects_bad_inputs():
    z=np.ones((4,4),dtype=float);valid=np.ones_like(z,bool)
    flag=Event();flag.set()
    with pytest.raises(TerrainCancelled):
        mfd_accumulation(z,valid,10,10,cancel=flag)
    with pytest.raises(RasterError,match="exponent"):
        mfd_accumulation(z,valid,10,10,exponent=0)
    valid[0,0]=False;z[1,1]=np.nan
    with pytest.raises(RasterError,match="finite"):
        mfd_accumulation(z,valid,10,10)


def test_strahler_two_equal_tributaries_raise_order_exactly_once():
    # Graph: (0,1)->2, (3,4)->5, (2,5)->6. The final outlet is order 3.
    destination=np.array([[2,2,6,5,5,6,-1]],dtype=np.int64)
    active=np.ones_like(destination,dtype=bool)
    order=strahler_orders(destination,active)
    np.testing.assert_array_equal(order,[[1,1,2,1,1,2,3]])


def test_strahler_ignores_lower_order_tributary_and_rejects_cycles():
    destinations=np.array([[2,2,4,4,-1]],dtype=np.int64)
    order=strahler_orders(destinations,np.ones_like(destinations,bool))
    np.testing.assert_array_equal(order,[[1,1,2,1,2]])
    with pytest.raises(RasterError,match="cycle"):
        strahler_orders(np.array([[1,0]]),np.ones((1,2),bool))
    with pytest.raises(RasterError,match="threshold"):
        strahler_orders(np.array([[-1]]),np.array([[False]]))


@pytest.fixture
def projected_dem(tmp_path):
    # Real GeoTIFF + WGS84 study polygon rather than an array-only mock.
    side=20;cell=10;affine=from_origin(500000,4500000,cell,cell)
    z=(300-np.indices((side,side))[0]*2
       -np.indices((side,side))[1]*3).astype(np.float32)
    path=tmp_path/"hydrology.tif"
    with rasterio.open(path,"w",driver="GTiff",width=side,height=side,
                       count=1,dtype="float32",crs="EPSG:32617",
                       transform=affine,nodata=-9999) as ds:
        ds.write(z,1)
    convert=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    corners=[(500010,4499990),(500190,4499990),
             (500190,4499810),(500010,4499810),(500010,4499990)]
    polygon={"type":"Polygon","coordinates":[[
        convert.transform(x,y) for x,y in corners]]}
    return path,polygon


@pytest.mark.parametrize("operation,expected_unit",[
    ("flow_accumulation_mfd","cell_equivalents"),
    ("stream_order","Strahler_order"),
])
def test_mfd_and_strahler_are_real_exported_products(projected_dem,operation,expected_unit):
    path,polygon=projected_dem
    result=run_terrain(path,polygon,operation,stream_cells=2)
    raster=result["raster"]
    assert raster["unit"]==expected_unit
    assert raster["valid_cells"]>0
    assert result["metrics"]["dataset_overlap_pct"]>99
    with MemoryFile(base64.b64decode(raster["geotiff"])) as memory:
        with memory.open() as source:
            z=source.read(1)
            assert source.tags()["TERRAIN_UNIT"]==expected_unit
            assert np.isfinite(z).any()
            if operation=="stream_order":
                assert int(np.nanmax(z))>=1
                assert all(level["label"].startswith("Order ")
                           for level in raster["legend"])
            else:
                assert np.nanmax(z)>np.nanmin(z)


def test_stream_order_high_threshold_is_explicit_error(projected_dem):
    path,polygon=projected_dem
    with pytest.raises(RasterError,match="No channel cells"):
        run_terrain(path,polygon,"stream_order",stream_cells=1000000)


def test_hydrology_products_are_reachable_through_advanced_api(projected_dem,tmp_path,monkeypatch):
    from shutil import copyfile
    from fastapi.testclient import TestClient
    from core.main import app
    from imagery.store import store_upload
    path,polygon=projected_dem
    root=tmp_path/"hydro-catalog"
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(root))
    copied=tmp_path/"hydro-api.tif"
    copyfile(path,copied)
    image=store_upload(copied,"hydro-api.tif")
    client=TestClient(app)
    for operation,unit in (("flow_accumulation_mfd","cell_equivalents"),
                           ("stream_order","Strahler_order")):
        response=client.post("/terrain/advanced",json={
            "image_id":image["id"],"geometry":polygon,"operation":operation,
            "stream_cells":2,"fill_sinks":True,
        })
        assert response.status_code==200,response.text
        product=response.json()
        assert product["raster"]["unit"]==unit
        assert product["source_crs"]=="EPSG:32617"
        assert product["metrics"]["product_valid_cells"]>0


def test_mfd_exponent_is_a_real_model_choice_and_recorded_in_output(projected_dem):
    z=np.array([[10.,8.,7.],[8.,4.,2.],[7.,2.,0.]])
    valid=np.ones(z.shape,bool)
    broad=mfd_accumulation(z,valid,10,10,exponent=.5)
    concentrated=mfd_accumulation(z,valid,10,10,exponent=6)
    assert np.nanmax(np.abs(broad-concentrated))>1e-3
    assert broad[-1,-1]==pytest.approx(9)
    assert concentrated[-1,-1]==pytest.approx(9)
    path,polygon=projected_dem
    result=run_terrain(path,polygon,"flow_accumulation_mfd",mfd_exponent=2.5)
    assert result["metrics"]["mfd_exponent"]==pytest.approx(2.5)
    assert result["algorithm_options"]["mfd_exponent"]==pytest.approx(2.5)
    assert "2.5" in result["warning"]



def test_shreve_adds_tributary_magnitudes_and_handles_cycles():
    from terrain.multiflow import shreve_magnitudes
    destinations=np.array([[2,2,6,5,5,6,-1]],dtype=np.int64)
    active=np.ones_like(destinations,bool)
    np.testing.assert_array_equal(shreve_magnitudes(destinations,active),[[1,1,2,1,1,2,4]])
    with pytest.raises(RasterError,match="cycle"):
        shreve_magnitudes(np.array([[1,0]]),np.ones((1,2),bool))


def test_shreve_real_geotiff_exports_true_integer_magnitudes(projected_dem):
    path,polygon=projected_dem
    result=run_terrain(path,polygon,"stream_order",stream_cells=2,
                       stream_order_scheme="shreve")
    assert result["algorithm_options"]["stream_order_scheme"]=="shreve"
    assert result["raster"]["unit"]=="Shreve_magnitude"
    assert result["metrics"]["max_stream_magnitude"]>=1
    with MemoryFile(base64.b64decode(result["raster"]["geotiff"])) as mem:
        with mem.open() as ds:
            assert ds.tags()["TERRAIN_UNIT"]=="Shreve_magnitude"
            values=ds.read(1)
            assert np.all(values[np.isfinite(values)]>=1)
