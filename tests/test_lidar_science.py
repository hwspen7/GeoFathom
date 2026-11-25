import csv
import io
import struct
import numpy as np
import pytest
from analysis.lidar_science import analyze, read_cloud, metric_crs

def table(result):
    return np.genfromtxt(io.StringIO(result["csv"]),delimiter=",",skip_header=1,ndmin=2)

def test_csv_and_crs():
    p, meta = read_cloud(b"x,y,z\n1,2,3\n4,5,6\n","a.csv")
    np.testing.assert_array_equal(p,[[1,2,3],[4,5,6]])
    assert len(meta["sha256"]) == 64
    assert metric_crs(32617) == "EPSG:32617"
    for code in (4326,2272):
        with pytest.raises(ValueError): metric_crs(code)
    for raw in (b"x,y,z\n1,nan,3\n",b"x,x,y,z\n1,2,3,4\n",b"x,y,z\n",b"x,y,z\n1,2\n"):
        with pytest.raises(ValueError): read_cloud(raw,"a.csv")

def test_las_scaled_coordinates_and_truncation():
    b = bytearray(227+40)
    b[:4]=b"LASF"; b[24]=1; b[25]=2
    struct.pack_into("<HI",b,94,227,227)
    b[104]=0
    struct.pack_into("<HI",b,105,20,2)
    struct.pack_into("<3d",b,131,.01,.02,.1)
    struct.pack_into("<3d",b,155,500000,4400000,100)
    struct.pack_into("<3i",b,227,100,-100,50)
    struct.pack_into("<3i",b,247,200,100,-50)
    p,_=read_cloud(bytes(b),"a.las")
    np.testing.assert_allclose(p,[[500001,4399998,105],[500002,4400002,95]])
    with pytest.raises(ValueError):read_cloud(bytes(b[:-1]),"a.las")
    b[104]=128
    with pytest.raises(ValueError):read_cloud(bytes(b),"a.las")

def test_quality_and_voxel_count_conservation():
    p=np.array([[.1,.1,.1],[.3,.3,.3],[1.2,.1,.1],[-.1,0,0],[.1,.1,.1]])
    assert analyze("quality",p)["metrics"]["unique_points"]==4
    r=table(analyze("voxel",p,size=1))
    assert r[:,3].sum()==len(p)
    np.testing.assert_allclose(r[1,:3],np.repeat(1/6,3))

def test_pca_plane_and_degenerate_line():
    x,y=np.meshgrid(np.arange(7.),np.arange(7.))
    p=np.column_stack((x.ravel(),y.ravel(),(2*x+3*y).ravel()))
    r=table(analyze("local_geometry",p,k=16))
    normal=np.array([-2,-3,1])/np.sqrt(14)
    np.testing.assert_allclose(r[:,3:6],np.tile(normal,(len(p),1)),atol=1e-10)
    assert np.max(r[:,6])<1e-6
    line=np.column_stack((np.arange(20.),np.zeros((20,2))))
    assert analyze("local_geometry",line,k=8)["metrics"]["valid_neighborhoods"]==0

def test_density_and_vertical_profile():
    p=np.array([[0.,0,0],[1,0,0],[3,0,1]])
    r=table(analyze("density",p,radius=1.1))
    np.testing.assert_array_equal(r[:,3],[1,1,0])
    np.testing.assert_allclose(r[:,4],r[:,3]/(4*np.pi*1.1**3/3))
    bins=table(analyze("vertical_profile",p,size=1))
    assert bins[:,1].sum()==3
    assert bins[:,2].sum()==pytest.approx(1)

def test_directed_distance_and_partial_surface_overlap():
    a=np.array([[.1,.1,4],[1.1,.1,2],[2.1,.1,8]])
    b=np.array([[.1,.1,1],[1.1,.1,3],[3.1,.1,0]])
    d=table(analyze("cloud_distance",a[:1],a[:1]+[0,0,2]))
    assert d[0,3]==pytest.approx(2)
    r=analyze("surface_change",a,b,size=1)
    assert r["metrics"]["shared_cells"]==2
    assert r["metrics"]["current_only_cells"]==1
    assert r["metrics"]["reference_only_cells"]==1
    assert r["metrics"]["net_volume_m3"]==2
    assert r["metrics"]["gain_volume_m3"]==3
    assert r["metrics"]["loss_volume_m3"]==1

def test_ground_tin_and_no_extrapolation():
    g=np.array([[0.,0,0],[2,0,2],[0,2,4],[2,2,6]])
    p=np.array([[.5,.5,4.5],[1,1,7],[3,3,10]])
    r=analyze("ground_height",p,g,max_edge=3)
    np.testing.assert_allclose(table(r)[:2,4],[3,4])
    assert r["metrics"]["unsupported_points"]==1
    assert r["rows"][2][-1] is None
    assert analyze("ground_height",p,g,max_edge=1)["metrics"]["valid_points"]==0

def test_failure_contracts():
    p=np.zeros((3,3))
    for op in ("cloud_distance","ground_height","surface_change"):
        with pytest.raises(ValueError):analyze(op,p)
    with pytest.raises(ValueError):analyze("local_geometry",p,k=4)
    with pytest.raises(ValueError):analyze("ground_height",p,p)
    with pytest.raises(ValueError):analyze("surface_change",p,p+100)
    with pytest.raises(ValueError):analyze("unknown",p)
    with pytest.raises(ValueError):analyze("quality",p,size=0)

def test_api_contract():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from analysis.lidar_routes import router
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    assert len(client.get("/analysis/lidar/catalog").json()["operations"])==35
    files={"cloud":("cloud.csv",b"x,y,z\n1,2,3\n","text/csv")}
    url="/analysis/lidar/run?operation=quality&epsg=32617&vertical_datum=local"
    r=client.post(url,files=files)
    assert r.status_code==200
    assert r.json()["receipt"]["horizontal_crs"]=="EPSG:32617"
    assert client.post(url.replace("32617","4326"),files=files).status_code==422
