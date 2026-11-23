"""On-demand 3D tiles: source exactness, continuity, holes, API and guardrails."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer
from imagery.raster import RasterError
from terrain.mesh_tiles import stream_mesh_tile


@pytest.fixture
def terrain_tile_dem(tmp_path):
    size=65
    y,x=np.indices((size,size))
    surface=(500+.25*x-0.1*y).astype("float32")
    surface[1,1]=-9999
    path=tmp_path/"lod-source.tif"
    transform=from_origin(500000,4500000,10,10)
    with rasterio.open(path,"w",driver="GTiff",width=size,height=size,
                       count=1,transform=transform,crs="EPSG:32617",
                       nodata=-9999,dtype="float32") as ds:
        ds.write(surface,1)
    t=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    ring=[t.transform(x,y) for x,y in [(500000,4500000),(500650,4500000),
          (500650,4499350),(500000,4499350),(500000,4500000)]]
    polygon={"type":"Polygon","coordinates":[ring]}
    return path,polygon,surface


def test_adjacent_source_tiles_share_exact_seam_cells(terrain_tile_dem):
    path,polygon,z=terrain_tile_dem
    left=stream_mesh_tile(path,polygon,1,0,0)
    right=stream_mesh_tile(path,polygon,1,0,1)
    assert left["col_indices"][-1]==right["col_indices"][0]==32
    assert left["row_indices"]==right["row_indices"]
    a=np.array(left["heights"],dtype=float).reshape(left["rows"],left["cols"])
    b=np.array(right["heights"],dtype=float).reshape(right["rows"],right["cols"])
    np.testing.assert_allclose(a[:,-1],b[:,0],atol=0)
    assert a[1,1]!=a[1,1] # genuine nodata, not interpolated
    assert left["source_elevation_unit"]=="m"
    assert left["grid_cell_width_m"]==10


def test_coarse_lod_masks_holes_between_valid_corners(terrain_tile_dem):
    path,polygon,_=terrain_tile_dem
    tile=stream_mesh_tile(path,polygon,4,0,0)
    assert tile["level"]==4 and tile["rows"]==17 and tile["cols"]==17
    assert tile["heights"][0] is not None
    assert tile["heights"][1] is not None
    assert tile["valid_quads"][0] is False
    assert any(tile["valid_quads"][1:])
    tile2=stream_mesh_tile(path,polygon,2,0,0)
    assert tile2["valid_quads"][0] is False
    assert tile2["heights"][0] is not None


@pytest.mark.parametrize("level,row,col",[(3,0,0),(1,-1,0),(1,0,-1),(1,50,50)])
def test_tile_budget_rejects_bad_level_or_coordinates(terrain_tile_dem,level,row,col):
    path,polygon,_=terrain_tile_dem
    with pytest.raises(RasterError):
        stream_mesh_tile(path,polygon,level,row,col)


def test_tile_route_matches_direct_reader_and_validates_requests(terrain_tile_dem,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from core.main import app
    from imagery.store import image_file, store_upload
    path,polygon,_=terrain_tile_dem
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path/"uploads"))
    image=store_upload(path,"mesh-lod-fixture.tif")
    client=TestClient(app)
    request={"image_id":image["id"],"geometry":polygon,
             "level":1,"tile_row":0,"tile_col":0}
    response=client.post("/terrain/mesh/tile",json=request)
    assert response.status_code==200,response.text
    # Store_upload deliberately moves the temporary GeoTIFF into the managed library.
    direct=stream_mesh_tile(image_file(image["id"]),polygon,1,0,0)
    assert response.json()["heights"]==direct["heights"]
    assert response.json()["valid_quads"]==direct["valid_quads"]
    bad=client.post("/terrain/mesh/tile",json={**request,"level":3})
    assert bad.status_code==422
    outside=client.post("/terrain/mesh/tile",json={**request,"tile_row":120})
    assert outside.status_code==422


def test_tile_reader_rejects_foreign_geography(terrain_tile_dem):
    path,polygon,_=terrain_tile_dem
    other={"type":"Polygon","coordinates":[[
        [-80,35],[-79,35],[-79,36],[-80,36],[-80,35]
    ]]}
    with pytest.raises(RasterError):
        stream_mesh_tile(path,other,1,0,0)


def test_streaming_tile_reports_exact_vertical_residuals(terrain_tile_dem):
    """LOD error is measured against source samples, never inferred from zoom."""
    path,polygon,_=terrain_tile_dem
    fine=stream_mesh_tile(path,polygon,1,0,0)
    coarse=stream_mesh_tile(path,polygon,4,0,0)
    assert fine["geometric_error_max_m"]==0
    assert fine["geometric_error_rmse_m"]==0
    assert fine["geometric_error_samples"]>0
    assert coarse["geometric_error_max_m"] is not None
    assert coarse["geometric_error_max_m"]<1e-4
    assert coarse["geometric_error_rmse_m"]<1e-4
    assert coarse["valid_quad_count"]==sum(coarse["valid_quads"])
    assert coarse["geometric_error_samples"]>0
    assert coarse["geometric_error_max_m"]>=coarse["geometric_error_rmse_m"]


def test_curved_terrain_has_measurable_lod_error(terrain_tile_dem):
    path,polygon,_=terrain_tile_dem
    with rasterio.open(path,"r+") as ds:
        heights=ds.read(1)
        yy,xx=np.indices(heights.shape)
        curved=heights+np.float32(0.05)*(xx*xx+yy*yy)
        curved[1,1]=ds.nodata
        ds.write(curved.astype("float32"),1)
    detailed=stream_mesh_tile(path,polygon,1,0,0)
    coarse=stream_mesh_tile(path,polygon,4,0,0)
    assert detailed["geometric_error_max_m"]==0
    assert coarse["geometric_error_max_m"]>0.1
    assert 0<coarse["geometric_error_rmse_m"]<=coarse["geometric_error_max_m"]
    assert coarse["valid_quad_count"]<len(coarse["valid_quads"])
