"""Fail-closed Terrain P0 analytical conformance gate.

The 95/100 score measures *controlled synthetic implementation conformance*,
not field-survey accuracy or a claim of 95% geospatial truth. Each of the 28
tools must independently pass two physics-based oracles. Shared GDAL and
numerical-invariant suites are separately enforced as infrastructure gates.
"""
import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from terrain.catalog import CORE_OPERATIONS


BENCHMARKS = (
    "test_p0_operation",
    "test_p0_flat_zero_gradient_and_no_fabricated_result",
)
MANDATORY_INVARIANTS = (
    "test_d8_upstream_mass_conserved_at_local_outlets",
    "test_viewshed_agrees_with_independent_scalar_ray_visibility",
    "test_priority_flood_preserves_true_height_and_reports_only_physical_fill",
    "test_flat_dijkstra_route_has_exact_theoretical_distance",
    "test_planar_contours_have_exact_interpolated_horizontal_coordinates",
    "test_p0_catalog_and_oracle_set_match_exactly",
    "test_local_utm_distances_pass_scientific_projection_gate",
    "test_high_latitude_web_mercator_is_rejected_as_quantitative_dem",
)


def read_junit(path):
    tree=ET.parse(path)
    status={}
    counts={"passed":0,"failed":0,"skipped":0}
    for test in tree.iter("testcase"):
        name=test.get("name","")
        if not name:
            continue
        skipped=test.find("skipped") is not None
        failed=any(test.find(t) is not None for t in ("failure","error"))
        passed=not skipped and not failed
        counts["skipped" if skipped else "failed" if failed else "passed"]+=1
        if name in status:
            raise ValueError(f"Duplicate test identity in P0 gate: {name}")
        status[name]=passed
    return status,counts


def evaluate(junit, gdaldem):
    test_status,counts=read_junit(junit)
    report=json.loads(Path(gdaldem).read_text(encoding="utf-8"))
    external=(report.get("passed") is True and
              len(report.get("tests",[]))>=7 and
              all(row["valid_compared"]>=5000 and
                  row["max_absolute_error"]<=row["maximum_allowed"]
                  for row in report["tests"]))
    invariants=all(test_status.get(key) is True
                   for key in MANDATORY_INVARIANTS)
    matrix=[]
    for operation in sorted(CORE_OPERATIONS):
        first=test_status.get(f"{BENCHMARKS[0]}[{operation}]") is True
        second=test_status.get(f"{BENCHMARKS[1]}[{operation}]") is True
        # 45/35 come from operation-specific numeric fixtures; the final
        # 20 points require independent GDAL and global invariant gates.
        # Shared gates are not misrepresented as operation-specific tests.
        score=(45*first + 35*second + 10*external + 10*invariants)
        matrix.append({"operation":operation,"analytic_dem_pass":first,
                       "flat_dem_pass":second,"p0_benchmark_score":score,
                       "meets_95_threshold":score>=95})
    passing=sum(item["meets_95_threshold"] for item in matrix)
    return {
        "schema_version":1,
        "assessment":"controlled_synthetic_numerical_implementation",
        "not_assessed":["survey_DTM_accuracy","vertical_datum_realization",
                        "all_real_world_landforms","full_operational_maturity",
                        "uncertainty_from_source_measurement"],
        "field_survey_certification":False,
        "required_minimum_score":95,
        "score_method":"45 analytic plane + 35 independent flat scene + 10 global GDAL gate + 10 common scientific invariants",
        "external_reference":report.get("reference_engine"),
        "external_comparisons_pass":external,
        "common_scientific_invariants_pass":invariants,
        "junit":counts,
        "operations_checked":len(matrix),
        "operations_meeting_threshold":passing,
        "minimum_score":min(item["p0_benchmark_score"] for item in matrix),
        "passed":len(matrix)==28 and passing==28 and external and invariants,
        "operations":matrix,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--junit",required=True)
    parser.add_argument("--reference",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    report=evaluate(args.junit,args.reference)
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",
                      encoding="utf-8")
    print(f"Terrain P0: {report['operations_meeting_threshold']}/28 at "
          f">=95 synthetic-conformance points; min={report['minimum_score']}")
    if not report["passed"]:
        for item in report["operations"]:
            if not item["meets_95_threshold"]:
                print("FAIL",item, file=sys.stderr)
        raise SystemExit("P0 95-point analytical acceptance gate FAILED")


if __name__=="__main__":
    main()
