"""Live PostgreSQL ownership fencing and isolated raster computation."""
import os,time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from jobs.distributed import Broker,worker_once,dispatch
from storage.snapshots import analysis_snapshot

pytestmark=pytest.mark.skipif(not os.getenv("GEOFATHOM_TEST_POSTGIS_DSN"),
                              reason="Live PostgreSQL service not configured.")

@pytest.fixture
def broker(monkeypatch):
    dsn=os.environ["GEOFATHOM_TEST_POSTGIS_DSN"]
    monkeypatch.setenv("GEOFATHOM_DISTRIBUTED_DSN",dsn)
    name="test-"+uuid4().hex
    monkeypatch.setenv("GEOFATHOM_DISTRIBUTED_QUEUE",name)
    obj=Broker(dsn,name)
    yield obj
    with obj.connect() as conn:
        conn.execute("DELETE FROM gf_distributed_jobs WHERE queue=%s",(name,))

def test_live_broker_claim_fencing_node_capacity_and_expiration(broker):
    uid,client=broker.submit({"kind":"spectral_index"})
    uid2,client2=broker.submit({"kind":"spectral_index"})
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims=list(pool.map(lambda _:broker.claim("same-node"),range(6)))
    active=[x for x in claims if x is not None]
    assert len(active)==1
    other=broker.claim("other-node")
    assert other and {active[0][0],other[0]}=={uid,uid2}
    claimed,owner,_=active[0]
    assert not broker.finish(claimed,"stale",result={"bad":True})
    assert broker.finish(claimed,owner,result={"good":True})
    token=client if claimed==uid else client2
    assert broker.poll(claimed,token)["result"]=={"good":True}
    with broker.connect() as c:
        c.execute("UPDATE gf_distributed_jobs SET worker_until=now()-interval '1 second' WHERE id=%s",(other[0],))
    assert not broker.heartbeat(other[0],other[1])
    assert not broker.finish(other[0],other[1],result={"bad":True})
    assert broker.poll(other[0],client if other[0]==uid else client2)["status"]=="interrupted"

def test_distributed_real_raster_pipeline(broker,tmp_path,monkeypatch):
    root=tmp_path/"catalog";root.mkdir()
    archive=tmp_path/"versions";archive.mkdir()
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(root))
    monkeypatch.setenv("GEOFATHOM_VERSION_DIR",str(archive))
    uid=str(uuid4())
    path=root/(uid+".tif")
    data=np.stack([np.full((128,128),200,np.uint8),np.full((128,128),50,np.uint8)])
    with rasterio.open(path,"w",driver="GTiff",width=128,height=128,count=2,
        dtype="uint8",crs="EPSG:4326",transform=from_origin(10,30,.00001,.00001)) as ds:
        ds.write(data)
    payload={"image_id":uid,"first_band":1,"second_band":2,"index":"ndvi",
             "threshold":.3,"full_resolution":True,"tile_size":64}
    def submit():
        with analysis_snapshot("spectral_index",payload) as provenance:
            return dispatch("spectral_index",payload,provenance,lambda _:None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(submit)
        until=time.monotonic()+20
        while not future.done() and time.monotonic()<until:
            if worker_once(broker,"test-node",archive):
                break
            time.sleep(.1)
        result=future.result(timeout=20)
    assert result["classified_pixels"]==128*128
    assert result["valid_pixels"]==128*128
    assert len(result["features"])==1
    assert len(list(archive.glob("*/*")))==1


def test_live_cancellation_fences_late_worker_and_prunes_terminal_rows(broker):
    uid, token = broker.submit({"kind": "spectral_index"})
    claimed = broker.claim("cancel-node")
    assert claimed[0] == uid
    owner = claimed[1]
    broker.cancel(uid, "not-the-client")
    assert broker.heartbeat(uid, owner)
    broker.cancel(uid, token)
    assert broker.poll(uid, token)["status"] == "cancelled"
    assert not broker.heartbeat(uid, owner)
    assert not broker.finish(uid, owner, result={"late": True})
    with broker.connect() as conn:
        conn.execute("UPDATE gf_distributed_jobs SET updated=now()-interval '31 days' WHERE id=%s", (uid,))
    assert broker.prune(30) == 1
    with pytest.raises(RuntimeError, match="lease lost"):
        broker.poll(uid, token)


def test_live_client_expiry_and_result_limit(broker):
    uid, token = broker.submit({"kind": "spectral_index"})
    _, owner, _ = broker.claim("size-node")
    assert broker.finish(uid, owner, result={"oversize": "x" * 5_000_001})
    row = broker.poll(uid, token)
    assert row["status"] == "failed" and "5 MB" in row["error"]
    uid, token = broker.submit({"kind": "spectral_index"})
    _, owner, _ = broker.claim("size-node")
    with broker.connect() as conn:
        conn.execute("UPDATE gf_distributed_jobs SET client_until=now()-interval '1 second' WHERE id=%s", (uid,))
    assert not broker.heartbeat(uid, owner)
    assert not broker.finish(uid, owner, result={"late": True})
    assert broker.poll(uid, token)["status"] == "interrupted"


def test_live_probe_through_independent_worker_process(broker,tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    from scripts.distributed_acceptance import coordinator
    archive=tmp_path/"shared";archive.mkdir()
    root=Path(__file__).resolve().parents[1]
    code=("from jobs.distributed import configured_broker; "
          "from scripts.distributed_acceptance import worker; "
          "import sys; worker(configured_broker(),sys.argv[1],sys.argv[2],60)")
    # The worker entry itself spawns a real raster child. A -c launcher has
    # no stdin pseudo-file and is safe provided the target is importable.
    process=subprocess.Popen([sys.executable,"-c",code,str(archive),"independent-node"],
                             cwd=root)
    try:
        report=coordinator(broker,archive,"independent-node",60)
        assert report["passed"] and report["valid_pixels"]==128*128
        assert report["physical_host_verified"] is False
        assert process.wait(timeout=15)==0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
