"""The P0 95-point gate must fail on missing evidence, not award phantom scores."""
import json
from xml.etree import ElementTree as ET

from scripts.terrain_numerical_gate import (
    BENCHMARKS, MANDATORY_INVARIANTS, evaluate
)
from terrain.catalog import CORE_OPERATIONS


def _artifacts(tmp_path, missing=None, gdal_success=True):
    root=ET.Element("testsuites")
    suite=ET.SubElement(root,"testsuite",name="p0")
    for op in sorted(CORE_OPERATIONS):
        for prefix in BENCHMARKS:
            name=f"{prefix}[{op}]"
            if name!=missing:
                ET.SubElement(suite,"testcase",name=name)
    for name in MANDATORY_INVARIANTS:
        if name!=missing:
            ET.SubElement(suite,"testcase",name=name)
    junit=tmp_path/"junit.xml"
    ET.ElementTree(root).write(junit,encoding="utf-8")
    jsonfile=tmp_path/"gdal.json"
    jsonfile.write_text(json.dumps({"passed":gdal_success,
        "reference_engine":"GDAL unit fixture",
        "tests":[{"valid_compared":9588,
                  "max_absolute_error":0.01,
                  "maximum_allowed":0.02} for i in range(7)]}))
    return junit,jsonfile


def test_28_operations_have_provable_nonrounded_95_point_gate(tmp_path):
    junit,reference=_artifacts(tmp_path)
    matrix=evaluate(junit,reference)
    assert matrix["passed"] is True
    assert matrix["operations_checked"]==28
    assert matrix["operations_meeting_threshold"]==28
    assert matrix["minimum_score"]==100
    assert all(item["p0_benchmark_score"]==100 for item in matrix["operations"])
    assert matrix["field_survey_certification"] is False


def test_missing_one_operation_degrades_it_below_95(tmp_path):
    op=sorted(CORE_OPERATIONS)[5]
    junit,reference=_artifacts(tmp_path,missing=f"{BENCHMARKS[1]}[{op}]")
    matrix=evaluate(junit,reference)
    assert matrix["passed"] is False
    assert matrix["operations_meeting_threshold"]==27
    assert matrix["minimum_score"]==65
    assert next(item for item in matrix["operations"] if item["operation"]==op)["meets_95_threshold"] is False


def test_failed_gdal_is_a_hard_stop_even_if_28_operational_oracles_pass(tmp_path):
    junit,reference=_artifacts(tmp_path,gdal_success=False)
    matrix=evaluate(junit,reference)
    assert not matrix["passed"]
    assert matrix["minimum_score"]==90
    assert matrix["operations_meeting_threshold"]==0


def test_missing_domain_invariant_prevents_all_95_certificates(tmp_path):
    junit,reference=_artifacts(
        tmp_path,missing="test_d8_upstream_mass_conserved_at_local_outlets")
    matrix=evaluate(junit,reference)
    assert matrix["minimum_score"]==90
    assert matrix["operations_meeting_threshold"]==0
    assert not matrix["common_scientific_invariants_pass"]
