import os
import pytest
from jobs.resources import configure_child

def test_invalid_cpu_affinity_and_gpu_address_limit(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_CPU_CORES_PER_WORKER","100")
    with pytest.raises(ValueError,match="cores"):
        configure_child()
    monkeypatch.setenv("GEOFATHOM_CPU_CORES_PER_WORKER","0")
    monkeypatch.setenv("GEOFATHOM_RASTER_AS_MB","2048")
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE","cuda")
    with pytest.raises(RuntimeError,match="CPU-only"):
        configure_child()

def test_real_affinity_on_spawned_child(tmp_path,monkeypatch):
    import psutil,subprocess,sys,json
    proc=psutil.Process()
    if not hasattr(proc,"cpu_affinity"):
        pytest.skip("Platform lacks CPU affinity.")
    result=subprocess.run([sys.executable,"-c",
        "from jobs.resources import configure_child; configure_child(); import psutil,json; print(json.dumps(psutil.Process().cpu_affinity()))"],
        env={**os.environ,"GEOFATHOM_CPU_CORES_PER_WORKER":"1","GEOFATHOM_RASTER_AS_MB":"0"},
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert len(json.loads(result.stdout))==1
