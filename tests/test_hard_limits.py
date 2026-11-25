import os
import sys
import subprocess
import json
from uuid import uuid4
import pytest
from jobs.hard_limits import requested_budget,enforce

def test_hard_limit_config_fails_closed(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_WORKER_MEMORY_MB","0")
    assert enforce("disabled") is None
    monkeypatch.setenv("GEOFATHOM_WORKER_MEMORY_MB","1")
    with pytest.raises(ValueError):requested_budget()
    if sys.platform.startswith("linux"):
        monkeypatch.setenv("GEOFATHOM_WORKER_MEMORY_MB","512")
        monkeypatch.delenv("GEOFATHOM_WORKER_CGROUP",raising=False)
        with pytest.raises(RuntimeError,match="cgroup"):
            enforce("not-delegated")

@pytest.mark.skipif(os.name!="nt",reason="Windows kernel Job Object acceptance")
def test_windows_real_combined_commit_limit():
    env={**os.environ,"GEOFATHOM_WORKER_MEMORY_MB":"256",
         "GEOFATHOM_WORKER_MEMORY_GROUP":"test-"+uuid4().hex}
    code="""from jobs.hard_limits import enforce
import json
result=enforce('test')
try:
    x=bytearray(512*1024**2)
except MemoryError:
    result['denied']=True
else:
    result['denied']=False
print(json.dumps(result))
"""
    result=subprocess.run([sys.executable,"-c",code],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    record=json.loads(result.stdout)
    assert record=={"mechanism":"windows-job-memory","limit_bytes":256*1024**2,"denied":True}
