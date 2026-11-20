"""Indexed snapping must agree with simple metric distance, with native required in CI."""
import os
import math
import pytest

from geometry.spatial import SegmentIndex


def test_spatial_index_queries():
    segments=[((float(i*10),0.0),(float(i*10),100.0)) for i in range(100_000)]
    with SegmentIndex(segments) as index:
        if os.getenv("GEOFATHOM_REQUIRE_NATIVE")=="1":
            assert index.engine=="cpp-bvh"
        for i in range(0,100_000,307):
            out=index.query(i*10+0.3,40,2.0)
            assert out is not None
            assert out["segment"]==i
            assert out["point"][0]==pytest.approx(i*10)
            assert out["distance_m"]==pytest.approx(0.3)
        assert index.query(-10000,-10000,1.0) is None


def test_spatial_index_validates_bad_data():
    with pytest.raises(ValueError):
        SegmentIndex([((float('nan'),1),(0,0))])
    with SegmentIndex([((0.,0.),(10.,0.))]) as index:
        with pytest.raises(ValueError):
            index.query(1,1,-2)
        assert index.query(5,1,2)["point"]==(5,0)
