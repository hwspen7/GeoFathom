"""Read measured coverage and hardware performance without inflating results."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def percent(covered, total):
    if total <= 0 or not 0 <= covered <= total:
        raise ValueError("Coverage report has no valid measured denominator.")
    return 100 * covered / total


def python_coverage(path):
    totals = read_json(path)["totals"]
    return {
        "statements": percent(totals["covered_lines"], totals["num_statements"]),
        "branches": percent(totals["covered_branches"], totals["num_branches"]),
    }


def native_coverage(path):
    root = ET.parse(path).getroot()
    return {"lines": percent(int(root.attrib["lines-covered"]), int(root.attrib["lines-valid"])),
            "branches": percent(int(root.attrib["branches-covered"]), int(root.attrib["branches-valid"]))}


def frontend_coverage(path):
    totals = read_json(path)["total"]
    return {name: percent(totals[name]["covered"], totals[name]["total"])
            for name in ("statements", "branches", "functions", "lines")}


# Targets are explicit, independent numerators/denominators, without rounding.
COVERAGE_TARGETS = {
    "python.statements":95.0, "python.branches":90.0,
    "native_cpu.lines":95.0, "native_cpu.branches":85.0,
    "web.statements":90.0, "web.branches":85.0,
}


def coverage_gates(metrics,baseline=None,required=None):
    """Qualify every required metric and reject invalid or missing values."""
    chosen=COVERAGE_TARGETS if required is None else required
    checks={}
    measurements={}
    for key in chosen:
        group,field=key.split(".")
        value=metrics[group][field]
        if (type(value) not in (int,float) or not math.isfinite(value)
                or not 0<=value<=100):
            raise ValueError(f"Invalid coverage metric: {key}")
        minimum=COVERAGE_TARGETS[key]
        measurements[key]={"actual":value,"minimum":minimum}
        checks[key]=value>=minimum
        if baseline and key in baseline:
            floor=baseline[key]
            if type(floor) not in (int,float) or not math.isfinite(floor) or not 0<=floor<=100:
                raise ValueError(f"Invalid regression baseline: {key}")
            checks[key+".no_regression"]=value>=floor
            measurements[key]["baseline"]=floor
    return {"passed":bool(checks) and all(checks.values()),"gates":checks,
            "measurements":measurements}


def compare_performance(baseline, current, metadata, tolerance):
    baseline, current = Path(baseline), Path(current)
    prior = read_json(baseline / "acceptance.json")
    if prior.get("passed") is not True:
        raise ValueError("Performance baseline is not a passed host report.")
    for key in ("gpu", "cpu", "logical_cpu_count", "python_version", "soak_seconds_per_device"):
        if prior.get(key) is None or prior[key] != metadata.get(key):
            raise ValueError(f"Incomparable performance baseline: {key}")
    measurements = {}
    for file, metric, direction in (("cpu-soak.json", "pixels_per_second", 1),
                                     ("cuda-soak.json", "pixels_per_second", 1),
                                     ("gpu-inference.json", "p95_latency_ms", -1)):
        previous = read_json(baseline / file)[metric]
        observed = read_json(current / file)[metric]
        if not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in (previous, observed)):
            raise ValueError("Invalid performance measurements.")
        regression = direction * (previous-observed) / previous * 100
        measurements[file] = {"metric": metric, "baseline": previous, "observed": observed,
                              "regression_percent": regression, "passed": regression <= tolerance}
    return {"passed": all(x["passed"] for x in measurements.values()), "measurements": measurements}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--web", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline",type=Path,help="Measured like-for-like coverage floors (metric to percent)")
    parser.add_argument("--report-only", action="store_true",
                        help="Collect CI measurements without asserting release qualification")
    args = parser.parse_args()
    py, native, web = python_coverage(args.python), native_coverage(args.native), frontend_coverage(args.web)
    metrics={"python":py,"native_cpu":native,"web":web}
    baseline=read_json(args.baseline)["floors"] if args.baseline else None
    result={**metrics,**coverage_gates(metrics,baseline)}
    data = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(data, encoding="utf-8")
    print(data)
    if not result["passed"] and not args.report_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
