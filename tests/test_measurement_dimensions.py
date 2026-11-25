from geometry.measure import measure_geometry
import pytest

def test_map_dimension_labels_use_ellipsoid():
    g={"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    result=measure_geometry(g)
    assert len(result["edge_lengths_m"])==4
    assert result["edge_lengths_m"][0]==pytest.approx(111319.490793,abs=.001)
    assert sum(result["edge_lengths_m"])==pytest.approx(result["perimeter_m"],abs=.001)

def test_dimension_label_payload_is_bounded():
    result=measure_geometry({"type":"LineString","coordinates":[[i/10000,0] for i in range(100)]})
    assert len(result["edge_lengths_m"])==48
