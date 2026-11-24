"""Audit GitHub file/directory commit checks without altering repository history."""
import csv
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


def git(*args):
    return subprocess.check_output(["git", *args]).decode("utf-8", "surrogateescape").strip()


def api(path):
    url = os.environ.get("GITHUB_API_URL", "https://api.github.com") + path
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def classify(checks, statuses):
    failures = {"failure", "timed_out", "action_required", "startup_failure", "stale"}
    adverse = [c["name"] + ": " + str(c.get("conclusion")) for c in checks if c.get("conclusion") in failures]
    adverse += [s["context"] + ": " + s["state"] for s in statuses if s["state"] in {"failure", "error"}]
    cancelled = [c["name"] for c in checks if c.get("conclusion") == "cancelled"]
    pending = any(c.get("status") != "completed" for c in checks) or any(s["state"] == "pending" for s in statuses)
    if adverse:
        return "failed", adverse + ["cancelled: " + c for c in cancelled]
    if cancelled:
        return "cancelled", cancelled
    if pending:
        return "pending", []
    if any(c.get("conclusion") == "success" for c in checks) or any(s["state"] == "success" for s in statuses):
        return "passed", []
    return "no_success_record", []


def inspect_commit(repo, sha):
    checks = []
    page = 1
    while True:
        batch = api(f"/repos/{repo}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}")["check_runs"]
        checks.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    statuses = api(f"/repos/{repo}/commits/{sha}/status")["statuses"]
    state, reasons = classify(checks, statuses)
    return state, reasons


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    head = git("rev-parse", ref)
    raw = subprocess.check_output(["git", "ls-tree", "-r", "-t", "-z", "--name-only", head])
    paths = [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]
    paths = sorted(set(paths)) + ["."]
    groups = defaultdict(list)
    for path in paths:
        sha = head if path == "." else git("log", "-1", "--format=%H", head, "--", path)
        if not sha:
            raise RuntimeError(f"No path commit found: {path}")
        groups[sha].append(path)
    rows = []
    errors = []
    for sha, members in groups.items():
        try:
            state, reasons = inspect_commit(repo, sha)
        except Exception as exc:
            state, reasons = "unverified", [str(exc)]
            errors.append(sha)
        for path in members:
            rows.append({"path": path, "last_commit": sha, "state": state, "reasons": "; ".join(reasons)})
        print(f"{sha[:12]} {state}: {len(members)} paths", flush=True)
    rows.sort(key=lambda row: row["path"])
    counts = Counter(row["state"] for row in rows)
    report = Path("file-check-audit")
    report.mkdir(exist_ok=True)
    with (report / "paths.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "last_commit", "state", "reasons"])
        writer.writeheader()
        writer.writerows(rows)
    (report / "report.json").write_text(json.dumps({"head": head, "counts": dict(counts), "distinct_commits": len(groups), "paths": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = [f"## File and directory check audit: {head[:12]}", "", f"Paths: {len(rows)}; unique commits: {len(groups)}", "", "| Status | Paths |", "|---|---:|"]
    summary.extend(f"| {key} | {value} |" for key, value in sorted(counts.items()))
    summary.extend(["", "Historical check status is not proof of a current source defect. No status is fabricated or overwritten. Inspect the CSV for every path."])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write("\n".join(summary) + "\n")
    print("\n".join(summary))
    if errors:
        raise SystemExit(f"Audit incomplete: {len(errors)} commit checks could not be retrieved")


if __name__ == "__main__":
    main()
