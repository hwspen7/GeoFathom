"""Independent GIS network face-detection acceptance tests."""
import pytest
from geometry.measure import GeometryError
from geometry.polygonize import polygonize_network


def edge(a,b):
    return {"type":"LineString","coordinates":[a,b]}


def three_adjacent_areas(offset=0.0):
    """Three adjacent one-kilometre polygons, topologically shared edges."""
    d=.01
    return [
        edge([0,0],[3*d,0]),
        edge([3*d,0],[3*d,d]),
        edge([3*d,d],[0,d]),
        edge([0,d],[0,0]),
        edge([d,offset],[d,d]),
        edge([2*d,0],[2*d,d]),
    ]


def test_shared_line_network_produces_three_distinct_measurable_faces():
    out=polygonize_network(three_adjacent_areas())
    assert out["count"]==3
    assert out["dangles"]==0 and out["cuts"]==0
    assert len({round(f["measurement"]["area_m2"]) for f in out["faces"]})<=2
    assert all(f["geometry"]["type"]=="Polygon" for f in out["faces"])
    assert all(f["measurement"]["perimeter_m"]>0 for f in out["faces"])
    assert sum(f["measurement"]["area_m2"] for f in out["faces"])==pytest.approx(out["area_m2"])
    assert all(f["properties"]["source_type"]=="polygonized_network" for f in out["faces"])


def test_crossing_lines_are_noded_not_silently_discarded():
    shell={"type":"Polygon","coordinates":[[[0,0],[.02,0],[.02,.02],[0,.02],[0,0]]]}
    cuts=[edge([.01,0],[.01,.02]),edge([0,.01],[.02,.01])]
    out=polygonize_network([shell,*cuts])
    assert out["count"]==4
    assert out["dangles"]==0 and out["invalid_rings"]==0
    assert all(f["measurement"]["area_m2"]>10000 for f in out["faces"])


def test_open_lines_report_no_area_and_dangling_geometry():
    out=polygonize_network([edge([0,0],[.01,0]),edge([.02,.01],[.03,.01])])
    assert out["count"]==0
    assert out["area_m2"]==0
    assert out["dangles"]+out["cuts"]>=1


def test_t_junction_snap_tolerance_is_explicit_and_restores_faces():
    d=.01
    paths=three_adjacent_areas()
    paths[4]=edge([d,.0000002],[d,d]) # 2 cm offset at shared boundary
    unsnapped=polygonize_network(paths,tolerance_m=0)
    snapped=polygonize_network(paths,tolerance_m=1)
    assert unsnapped["count"]<3
    assert snapped["count"]==3


def test_line_network_does_not_change_original_inputs():
    inputs=three_adjacent_areas()
    import copy
    before=copy.deepcopy(inputs)
    polygonize_network(inputs)
    assert inputs==before


@pytest.mark.parametrize("options", [
    {"tolerance_m":-1}, {"tolerance_m":21}, {"tolerance_m":float("nan")},
    {"minimum_area_m2":float("inf")}, {"max_faces":0},
])
def test_invalid_numeric_controls_fail_closed(options):
    with pytest.raises(GeometryError):
        polygonize_network(three_adjacent_areas(),**options)


def test_face_limit_fails_rather_than_silently_truncating_results():
    with pytest.raises(GeometryError,match="Detected"):
        polygonize_network(three_adjacent_areas(),max_faces=2)


def test_point_anchors_are_not_misrepresented_as_closed_areas():
    point={"type":"Point","coordinates":[1,1]}
    out=polygonize_network([point,edge([0,0],[.01,0])])
    assert out["count"]==0
    with pytest.raises(GeometryError,match="no edges"):
        polygonize_network([point])


def test_network_endpoint_rejects_unknown_types_and_unbounded_coordinates():
    with pytest.raises(GeometryError):
        polygonize_network([{"type":"GeometryCollection","geometries":[]}])
    with pytest.raises(GeometryError,match="WGS84"):
        polygonize_network([edge([190,0],[191,1])])
