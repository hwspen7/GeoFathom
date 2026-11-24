import io
import numpy as np
import pytest
from analysis.lidar_uncertainty import correlated_change

def test_correlated_volume_known_two_cells():
    p=np.array([[.1,.1,1],[.2,.2,1],[.3,.3,1],[1.1,.1,1],[1.2,.2,1],[1.3,.3,1]])
    rows,m=correlated_change(p+[0,0,2],p,1.,.5,2.,3)
    assert m["net_volume_m3"]==pytest.approx(4)
    assert m["volume_standard_uncertainty_m3"]==pytest.approx(.5*np.sqrt(2+2*np.exp(-.5)))
    np.testing.assert_allclose(rows[:,4],2)
    with pytest.raises(ValueError):correlated_change(p,p+[100,0,0],1.,.5,2.,3)

def test_laz_stream_count_and_crs(monkeypatch):
    laspy=pytest.importorskip("laspy")
    from pyproj import CRS
    from analysis import lidar_disk
    h=laspy.LasHeader(point_format=3,version="1.2")
    h.scales=np.array([.01,.01,.01]);h.offsets=np.array([0.,0.,0.])
    h.add_crs(CRS.from_epsg(32617))
    las=laspy.LasData(h)
    las.x=[.1,.2,.3,1.1];las.y=[.1,.2,.3,.1];las.z=[.1,.2,.3,.1]
    las.classification=np.array([2,2,5,5],dtype=np.uint8)
    las.return_number=np.array([1,1,2,1],dtype=np.uint8)
    b=io.BytesIO();las.write(b,do_compress=True)
    monkeypatch.setattr(lidar_disk,"CHUNK",2)
    table,m=lidar_disk.stream_voxels(b,32617,1.)
    assert m["input_points"]==4
    assert m["classification_counts"]=={"2":2,"5":2}
    np.testing.assert_allclose(table[:,3],[3,1])
    np.testing.assert_allclose(table[0,:3],[.2,.2,.2])
    np.testing.assert_allclose(table[0,4:],[.1,.3])
    b.seek(0);p,meta=lidar_disk.read_compressed(b,32617,100)
    assert meta["compressed"]
    assert len(p)==4
    with pytest.raises(ValueError,match="conflicts"):lidar_disk.stream_voxels(b,32618,1.)
