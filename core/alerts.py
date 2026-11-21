"""Persistent, at-least-once delivery of operational alert transitions.

Run as a separate operator service, never inside a request handler. No tokens,
filesystem paths, job contents or raw exception text enter the notification.
The receiver may deduplicate the stable event_id after an ambiguous timeout.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import uuid4
import httpx

KNOWN={"LOW_DISK","INTERRUPTED_JOBS","API_UNAVAILABLE","HIGH_ERROR_RATE","HIGH_RSS"}

def _endpoint(url,local=False):
    p=urlsplit(url)
    if (not p.hostname or p.username or p.password or p.fragment
            or (p.scheme!="https" and not (local and p.scheme=="http"
                and p.hostname in {"localhost","127.0.0.1","::1"}))):
        raise ValueError("Invalid alert endpoint; HTTPS is required outside loopback.")
    return url

class AlertRelay:
    def __init__(self,state_file,webhook,client):
        self.path=Path(state_file)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.webhook=_endpoint(webhook)
        self.client=client
        with closing(self._connect()) as db,db:
            db.execute("""CREATE TABLE IF NOT EXISTS alert_states(
                code TEXT PRIMARY KEY,active INTEGER NOT NULL,event_id TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0)""")

    def _connect(self):
        return sqlite3.connect(self.path,timeout=30)

    def reconcile(self,codes):
        codes=set(codes)
        if not codes<=KNOWN:
            raise ValueError("Unknown alert code.")
        # A single transaction also serializes delivery by independent relays.
        # Retrying unacknowledged events uses the same ID on each attempt.
        sent=0
        with closing(self._connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            rows={r[0]:r[1] for r in db.execute("SELECT code,active FROM alert_states")}
            for code in sorted(codes|set(rows)):
                active=int(code in codes)
                if rows.get(code,0)!=active:
                    db.execute("""INSERT INTO alert_states VALUES(?,?,?,0)
                        ON CONFLICT(code) DO UPDATE SET active=excluded.active,
                        event_id=excluded.event_id,delivered=0""",(code,active,uuid4().hex))
        # Commit the transition before performing network I/O so failed
        # deliveries survive a process restart.
        for code in sorted(KNOWN):
            with closing(self._connect()) as db,db:
                db.execute("BEGIN IMMEDIATE")
                event=db.execute("""SELECT active,event_id FROM alert_states
                    WHERE code=? AND delivered=0""",(code,)).fetchone()
                if not event:continue
                active,event_id=event
                try:
                    response=self.client.post(self.webhook,json={
                        "service":"GeoFathom","code":code,
                        "state":"firing" if active else "resolved","event_id":event_id,
                    },headers={"Idempotency-Key":event_id},follow_redirects=False)
                    response.raise_for_status()
                except httpx.HTTPError:
                    continue
                db.execute("UPDATE alert_states SET delivered=1 WHERE event_id=?",(event_id,))
                sent+=1
        return sent

def check_metrics(client,url,token,rss_limit_mb=4096,error_rate=.1):
    """Evaluate bounded operational metrics; treat inaccessible API as failure."""
    try:
        with client.stream("GET",_endpoint(url,local=True),
                headers={"X-GeoFathom-API-Key":token},follow_redirects=False) as reply:
            reply.raise_for_status()
            data=bytearray()
            for block in reply.iter_bytes():
                data.extend(block)
                if len(data)>65536:raise ValueError("Oversized metrics response.")
        state=json.loads(data)
        codes=set(state["alerts"])&KNOWN
        req=state["requests"]
        if req["total"]>=20 and req["server_errors"]/req["total"]>=error_rate:
            codes.add("HIGH_ERROR_RATE")
        if state["rss_bytes"]>=rss_limit_mb*1024**2:
            codes.add("HIGH_RSS")
        return codes
    except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
        return {"API_UNAVAILABLE"}

def main():
    parser=argparse.ArgumentParser(description="Deliver operational alerts")
    parser.add_argument("--state",type=Path,required=True)
    parser.add_argument("--metrics",default="http://127.0.0.1:8000/health/metrics")
    parser.add_argument("--interval",type=int,default=30)
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args()
    if not 5<=args.interval<=3600:parser.error("Interval must be 5–3600 seconds.")
    webhook=os.environ["GEOFATHOM_ALERT_WEBHOOK"]
    token=os.getenv("GEOFATHOM_API_TOKEN","")
    _endpoint(args.metrics,local=True)
    with httpx.Client(timeout=10,follow_redirects=False,trust_env=False) as client:
        relay=AlertRelay(args.state,webhook,client)
        while True:
            count=relay.reconcile(check_metrics(client,args.metrics,token))
            print(json.dumps({"delivered":count}),flush=True)
            if args.once:break
            time.sleep(args.interval)
if __name__=="__main__":
    main()
