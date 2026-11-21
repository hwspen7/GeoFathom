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


def test_spatial_index_rejects_queries_after_close_and_is_idempotent():
    index=SegmentIndex([((0.,0.),(10.,0.))])
    assert index.query(5.,1.,3.)["distance_m"]==pytest.approx(1.)
    index.close()
    index.close()
    with pytest.raises(ValueError,match="closed"):
        index.query(5.,1.,3.)
    with pytest.raises(ValueError,match="closed"):
        with index:
            pass


def test_batched_spatial_index_parity_and_no_match():
    segments=[((float(i*4),0.),(float(i*4),20.)) for i in range(500)]
    queries=[(float(i*4)+.25,10.) for i in range(0,500,7)]
    queries.extend([(-2000.,-2000.),(99999.,99999.)])
    with SegmentIndex(segments) as index:
        result=index.query_many(queries,1.)
        assert len(result)==len(queries)
        for point,batch in zip(queries,result):
            single=index.query(*point,1.)
            if single is None:
                assert batch is None
            else:
                assert batch is not None
                assert batch["segment"]==single["segment"]
                assert batch["point"]==pytest.approx(single["point"])
                assert batch["distance_m"]==pytest.approx(single["distance_m"])
        assert result[-2:] == [None,None]
        with pytest.raises(ValueError,match="finite XY"):
            index.query_many([[float("nan"),0]],1.)
        with pytest.raises(ValueError,match="finite XY"):
            index.query_many([],1.)
        with pytest.raises(ValueError,match="tolerance"):
            index.query_many([(0.,0.)],-1.)
    with pytest.raises(ValueError,match="closed"):
        index.query_many([(0.,0.)],1.)


def test_shared_native_index_safely_serializes_close_with_queries():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time
    from geometry.measure import GeometryError

    index=SegmentIndex([((float(i),0.),(float(i),10.)) for i in range(1500)])
    start=Event()
    def reader():
        start.wait(3)
        completed=0
        for i in range(300):
            try:
                output=index.query(float(i%100),5.,.5)
                assert output is not None
                completed+=1
            except GeometryError as error:
                assert "closed" in str(error)
                break
        return completed
    def closer():
        start.wait(3)
        time.sleep(.002)
        index.close()
    with ThreadPoolExecutor(max_workers=5) as executor:
        tasks=[executor.submit(reader) for _ in range(4)]
        owner=executor.submit(closer)
        start.set()
        owner.result(timeout=10)
        counts=[task.result(timeout=10) for task in tasks]
    assert all(0 <= n <= 300 for n in counts)
    assert index._handle is None
    with pytest.raises(GeometryError,match="closed"):
        index.query_many([(0.,0.)],1.)


def test_zero_tolerance_shapely_fallback_hits_exact_line(monkeypatch):
    import geometry.spatial as spatial
    monkeypatch.setattr(spatial,"_native",lambda:None)
    with spatial.SegmentIndex([((0.,0.),(10.,0.))]) as index:
        assert index.engine=="shapely-strtree"
        assert index.query(5.,0.,0.)["distance_m"]==0
        assert index.query_many([(5.,0.),(5.,.1)],0.)[1] is None
