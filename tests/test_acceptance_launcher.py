"""Test the official host report gate without running hardware or Docker."""
import importlib.util
from pathlib import Path

import pytest


def load_script(name):
    script = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("counts", [
    'tests="1" failures="1" errors="0" skipped="0"',
    'tests="2" failures="0" errors="1" skipped="0"',
    'tests="2" failures="0" errors="0" skipped="1"',
    'tests="0" failures="0" errors="0" skipped="0"',
])
def test_acceptance_rejects_incomplete_junit(tmp_path, counts):
    host = load_script("host_acceptance")
    path = tmp_path / "report.xml"
    path.write_text(f"<testsuites><testsuite {counts}/></testsuites>")
    with pytest.raises(RuntimeError, match="no skipped or failed"):
        host.check_junit(path)


def test_acceptance_counts_all_suites(tmp_path):
    host = load_script("host_acceptance")
    path = tmp_path / "report.xml"
    path.write_text('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"/>'
                    '<testsuite tests="3" failures="0" errors="0" skipped="0"/></testsuites>')
    assert host.check_junit(path) == {"tests": 5, "failures": 0, "errors": 0, "skipped": 0}


def test_acceptance_generator_creates_valid_manifest(tmp_path):
    # The minimal Windows CI does not require ONNX; the hosted full CI and
    # hardware acceptance both install it, so exercise generation when present.
    import os
    import json
    if os.getenv("GEOFATHOM_REQUIRE_REAL_ONNX") == "1":
        import onnx
    else:
        onnx = pytest.importorskip("onnx")
    model = load_script("acceptance_model")
    directory = model.create(tmp_path)
    onnx.checker.check_model(onnx.load(str(directory / "gpu_acceptance.onnx")))
    manifest = json.loads((directory / "gpu_acceptance.json").read_text())
    assert manifest["max_batch"] == 4 and manifest["bands"] == [1, 2, 3]
