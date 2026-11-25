"""Run a real raster broker probe across independent worker processes/hosts.

Provision a disposable PostGIS database and a shared archive supporting
atomic hard links. A remote node name is observed, not proof of separate
physical hardware. Use a unique acceptance queue on both machines.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def coordinator(broker, archive, expected_node, timeout=60):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from imagery.store import file_sha256
    from storage.versions import publish

    if not 10<=timeout<=3600:
        raise ValueError("Probe timeout must be 10–3600 seconds.")
    uid=str(uuid4())
    with TemporaryDirectory(prefix="geofathom-broker-probe-") as scratch:
        source=Path(scratch)/"acceptance.tif"
        data=np.stack([np.full((128,128),200,np.uint8),np.full((128,128),50,np.uint8)])
        with rasterio.open(source,"w",driver="GTiff",width=128,height=128,count=2,
            dtype="uint8",crs="EPSG:4326",transform=from_origin(10,30,.00001,.00001)) as ds:
            ds.write(data)
        digest=file_sha256(source)
        publish(archive,source,digest)
    payload={"image_id":uid,"first_band":1,"second_band":2,"index":"ndvi",
             "threshold":.3,"full_resolution":True,"tile_size":64}
    spec={"kind":"spectral_index","payload":payload,
          "provenance":{"source_sha256":{uid:digest},"model_files_sha256":{}}}
    task,token=broker.submit(spec)
    started=time.monotonic()
    try:
        while time.monotonic()-started<timeout:
            row=broker.poll(task,token)
            if row["status"]=="completed":
                with broker.connect() as conn:
                    owner=conn.execute("SELECT node FROM gf_distributed_jobs WHERE id=%s AND queue=%s",
                                       (task,broker.queue)).fetchone()
                result=row["result"]
                if not owner or owner["node"]!=expected_node:
                    raise RuntimeError("Probe completed on an unexpected compute node.")
                if (result["classified_pixels"]!=128*128 or result["valid_pixels"]!=128*128
                        or len(result["features"])!=1):
                    raise RuntimeError("Remote raster numerical acceptance failed.")
                return {"passed":True,"coordinator_hostname":socket.gethostname(),
                        "observed_compute_node":owner["node"],"physical_host_verified":False,
                        "archive_sha256":digest,"queue":broker.queue,"task":task,
                        "valid_pixels":result["valid_pixels"],"engine":result.get("engine"),
                        "seconds":time.monotonic()-started}
            if row["status"] not in ("queued","running"):
                raise RuntimeError(row["error"] or "Remote probe failed.")
            time.sleep(.25)
        raise RuntimeError("Remote acceptance probe timed out.")
    finally:
        broker.cancel(task,token)


def worker(broker, archive, node, timeout):
    from jobs.distributed import worker_once
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if worker_once(broker,node,archive):
            # Coordinator verifies both the result and the observed node.
            return
        time.sleep(.25)
    raise RuntimeError("No acceptance probe received within the deadline.")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("role",choices=["coordinator","worker"])
    parser.add_argument("--queue",required=True)
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--node",default=socket.gethostname())
    parser.add_argument("--expected-node")
    parser.add_argument("--timeout",type=int,default=120)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if not 10<=args.timeout<=3600 or not args.queue.startswith("acceptance-"):
        parser.error("Configure a unique acceptance-* queue and a 10–3600 second timeout.")
    if not args.archive.is_dir():
        parser.error("A provisioned shared archive directory is required.")
    if args.role=="coordinator" and (not args.expected_node or not args.output):
        parser.error("Coordinator requires --expected-node and --output.")
    dsn=os.getenv("GEOFATHOM_DISTRIBUTED_DSN")
    if not dsn:
        parser.error("Configure the disposable GEOFATHOM_DISTRIBUTED_DSN.")
    from jobs.distributed import Broker
    broker=Broker(dsn,args.queue)
    if args.role=="worker":
        worker(broker,args.archive,args.node,args.timeout)
        print("Worker probe attempt returned; check the coordinator report.")
    else:
        report=coordinator(broker,args.archive,args.expected_node,args.timeout)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
