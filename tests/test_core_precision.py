"""Independent numerical fixtures for the authoritative GIS measurement contract."""
import math
import pytest
from geometry.measure import measure_geometry,GeometryError
from geometry.editing import construct
from storage.crs import transform_positions
from storage.database import StorageError

def rectangle(x0,y0,x1,y1):
    return [[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]

def polygon(ring,*holes):
    return {"type":"Polygon","coordinates":[ring,*holes]}

@pytest.mark.parametrize("reverse_outer",[False,True])
@pytest.mark.parametrize("reverse_hole",[False,True])
def test_area_and_boundary_length_independent_of_ring_winding(reverse_outer,reverse_hole):
    outer=rectangle(0,0,1,1)
    hole=rectangle(.2,.2,.8,.8)
    whole=measure_geometry(polygon(outer))
    cut=measure_geometry(polygon(hole))
    result=measure_geometry(polygon(outer[::-1] if reverse_outer else outer,
        hole[::-1] if reverse_hole else hole))
    # GeographicLib WGS84 1-degree geodesic quadrilateral reference.
    assert whole["area_m2"]==pytest.approx(12308778361.469452,abs=.02)
    assert whole["perimeter_m"]==pytest.approx(443770.917248302,abs=.0001)
    assert result["area_m2"]==pytest.approx(whole["area_m2"]-cut["area_m2"],abs=.02)
    assert result["perimeter_m"]==pytest.approx(whole["perimeter_m"]+cut["perimeter_m"],abs=.0001)

def test_multipart_opposite_winding_cannot_cancel_area():
    a=rectangle(0,0,1,1)
    b=rectangle(2,0,3,1)
    result=measure_geometry({"type":"MultiPolygon","coordinates":[[a],[b[::-1]]]})
    assert result["area_m2"]==pytest.approx(2*12308778361.469452,abs=.04)
    assert result["perimeter_m"]==pytest.approx(2*443770.917248302,abs=.0002)

@pytest.mark.parametrize("latitude,expected",[(0,110574.3885578),(45,111141.5484742)])
def test_meridional_line_reference(latitude,expected):
    result=measure_geometry({"type":"LineString","coordinates":[[0,latitude],[0,latitude+1]]})
    assert result["length_m"]==pytest.approx(expected,abs=.001)

def test_circle_geodesic_radius_and_polygon_discretization():
    radius=100
    result=construct("circle",[[10,40]],radius_m=radius,segments=360)
    # For a small circle, chordal polygon discretization dominates the
    # ellipsoidal correction. Compare against the exact planar 360-gon.
    expected=180*radius**2*math.sin(2*math.pi/360)
    assert result["measurement"]["area_m2"]==pytest.approx(expected,rel=1e-6)
    assert result["measurement"]["perimeter_m"]==pytest.approx(720*radius*math.sin(math.pi/360),rel=1e-6)

@pytest.mark.parametrize("lon,lat",[(0,0),(10,45),(-83,40),(179,-80)])
def test_web_mercator_independent_closed_form_and_roundtrip(lon,lat):
    out=transform_positions([[lon,lat]],target="EPSG:3857")
    expected=[6378137*math.radians(lon),6378137*math.asinh(math.tan(math.radians(lat)))]
    assert out["coordinates"][0]==pytest.approx(expected,abs=1e-6)
    restored=transform_positions(out["coordinates"],source="EPSG:3857",target="EPSG:4326")
    assert restored["coordinates"][0]==pytest.approx([lon,lat],abs=1e-10)

def test_utm_central_meridian_control_point():
    result=transform_positions([[-81,0],[-81,40]],target="EPSG:32617")
    assert result["coordinates"][0]==pytest.approx([500000,0],abs=1e-6)
    assert result["coordinates"][1]==pytest.approx([500000,4427757.218738374],abs=.001)

@pytest.mark.parametrize("crs",["EPSG:4978","EPSG:4979","EPSG:5703","EPSG:7405"])
def test_2d_transform_rejects_unrepresentable_crs(crs):
    with pytest.raises(StorageError,match="unsupported EPSG"):
        transform_positions([[10,20]],target=crs)

@pytest.mark.parametrize("point",[[181,10],[0,91],[0,-91],[True,0],[float("nan"),0],[1,2,3],None])
def test_transform_rejects_invalid_coordinate_pairs(point):
    with pytest.raises(StorageError):
        transform_positions([point])
