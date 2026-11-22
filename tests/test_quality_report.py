"""Independent quality-gate math and false-green prevention."""
import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location("quality_report",
    Path(__file__).resolve().parents[1]/"scripts"/"quality_report.py")
quality=importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def write(path, payload):
    path.write_text(json.dumps(payload),encoding="utf-8")


def test_python_coverage_keeps_statement_and_branch_denominators_separate(tmp_path):
    path=tmp_path/"coverage.json"
    write(path,{"totals":{"covered_lines":95,"num_statements":100,
        "covered_branches":45,"num_branches":100}})
    assert quality.python_coverage(path)=={"statements":95,"branches":45}


@pytest.mark.parametrize("covered,total",[(0,0),(-1,10),(11,10)])
def test_invalid_coverage_cannot_be_reported_as_pass(covered,total):
    with pytest.raises(ValueError):
        quality.percent(covered,total)


def test_performance_gate_detects_both_latency_and_throughput_regression(tmp_path):
    baseline=tmp_path/"baseline";current=tmp_path/"current"
    baseline.mkdir();current.mkdir()
    meta={"gpu":"test","cpu":"test","logical_cpu_count":8,"python_version":"3.11",
          "soak_seconds_per_device":60}
    write(baseline/"acceptance.json",{**meta,"passed":True})
    for name,metric,before,after in (
        ("cpu-soak.json","pixels_per_second",100,90),
        ("cuda-soak.json","pixels_per_second",100,70),
        ("gpu-inference.json","p95_latency_ms",1,1.3)):
        write(baseline/name,{metric:before})
        write(current/name,{metric:after})
    result=quality.compare_performance(baseline,current,meta,15)
    assert not result["passed"]
    assert result["measurements"]["cpu-soak.json"]["passed"]
    assert not result["measurements"]["cuda-soak.json"]["passed"]
    assert not result["measurements"]["gpu-inference.json"]["passed"]
    with pytest.raises(ValueError,match="Incomparable"):
        quality.compare_performance(baseline,current,{**meta,"cpu":"different"},15)
