"""Run local Windows hardware, database, backend and browser acceptance.

Uses an isolated report directory and disposable PostGIS container by default.
No Python packages, GPU drivers or system tooling are silently installed.
"""
import argparse
import hashlib
import json
import os
import platform
import importlib.metadata
import secrets
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, env, cwd=ROOT, capture=False):
    print(">", " ".join(map(str, args)), flush=True)
    try:
        return subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True,
                              text=True, capture_output=capture)
    except subprocess.CalledProcessError as error:
        # Preserve diagnostics from captured subprocesses before propagating failure.
        if error.stdout:
            print(error.stdout, flush=True)
        if error.stderr:
            print(error.stderr, file=sys.stderr, flush=True)
        raise


def require(name, override=None):
    path = override or shutil.which(name)
    if not path or not Path(path).is_file():
        raise RuntimeError(f"Missing {name}; install it or correct the executable PATH.")
    return str(Path(path).resolve())


def build_native(directory, env, cuda=False):
    settings = ["-A", "x64", "-DBUILD_TESTING=ON", f"-DGEOFATHOM_NATIVE_CUDA={'ON' if cuda else 'OFF'}"]
    if cuda:
        settings.append("-DCMAKE_CUDA_ARCHITECTURES=89")
    run(["cmake", "-S", ROOT, "-B", directory, *settings], env)
    configs = ["Release"] if cuda else ["Release", "Debug"]
    for config in configs:
        run(["cmake", "--build", directory, "--config", config, "--parallel"], env)
        run(["ctest", "--test-dir", directory, "-C", config, "--output-on-failure",
             "--no-tests=error", "--output-log", directory / f"ctest-{config}.log"], env)
        if config == "Debug":
            run(["ctest", "--test-dir", directory, "-C", config, "--output-on-failure",
                 "--no-tests=error", "--repeat", "until-fail:20", "--output-log",
                 directory / "ctest-Debug-repeat.log"], env)
    dll = directory / "Release" / "geofathom_native.dll"
    if not dll.is_file():
        raise RuntimeError("Expected x64 Release native DLL missing.")
    return str(dll)


def sha256_file(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def save_report(out, report):
    temp=out/"acceptance.json.tmp"
    temp.write_text(json.dumps(report,indent=2),encoding="utf-8")
    temp.replace(out/"acceptance.json")


def stage_files(device):
    files=[f"native-{device}/Release/geofathom_native.dll",
           f"native-{device}/ctest-Release.log",f"{device}-soak.json"]
    if device=="cpu":
        files.extend(["native-cpu/ctest-Debug.log","native-cpu/ctest-Debug-repeat.log"])
    return files


def verify_resume_metadata(prior,current):
    if prior.get("tracked_tree_dirty") is not False or current.get("tracked_tree_dirty") is not False:
        raise ValueError("Resume requires clean source trees.")
    for key in ("git_commit","platform","gpu","cpu","logical_cpu_count",
                "python_version","package_versions","soak_seconds_per_device","toolchain"):
        if key not in prior or prior[key]!=current.get(key):
            raise ValueError(f"Resume run is incompatible: {key}")


def restore_native_stage(previous,out,prior,device):
    expected=prior.get("native_checkpoints",{}).get(device)
    if not expected:
        return False
    files=stage_files(device)
    if set(expected)!=set(files):
        raise ValueError("Incomplete native checkpoint evidence.")
    for name in files:
        source=previous/name
        if not source.is_file() or sha256_file(source)!=expected[name]:
            raise ValueError(f"Invalid native checkpoint artifact: {name}")
    soak=json.loads((previous/f"{device}-soak.json").read_text(encoding="utf-8"))
    if (soak.get("passed") is not True or soak.get("device")!=device
            or soak.get("seconds",0)<prior["soak_seconds_per_device"]):
        raise ValueError("Native checkpoint soak did not pass.")
    for name in files:
        target=out/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(previous/name,target)
    return True


def native_stage(device,out,env,report,seconds,previous=None,prior=None):
    resumed=bool(previous and restore_native_stage(previous,out,prior,device))
    if resumed:
        report.setdefault("resumed_stages",[]).append(device)
    else:
        env["GEOFATHOM_NATIVE_LIBRARY"]=build_native(out/f"native-{device}",env,cuda=device=="cuda")
        run([sys.executable,"benchmarks/soak.py","--seconds",seconds,
             "--device",device,"--output",out/f"{device}-soak.json"],env)
    env["GEOFATHOM_NATIVE_LIBRARY"]=str(out/f"native-{device}"/"Release"/"geofathom_native.dll")
    report.setdefault("native_checkpoints",{})[device]={name:sha256_file(out/name) for name in stage_files(device)}
    report["stages"].append(f"{device.upper()} native and soak")
    save_report(out,report)


def start_postgis(docker, name, env, state):
    password = secrets.token_urlsafe(24)
    docker_env = {**env, "POSTGRES_PASSWORD": password}
    run([docker, "run", "-d", "--rm", "--name", name,
         "-e", "POSTGRES_USER=geofathom", "-e", "POSTGRES_PASSWORD",
         "-e", "POSTGRES_DB=geofathom", "-p", "127.0.0.1::5432",
         "postgis/postgis:16-3.4"], docker_env)
    state["container_started"] = True
    port = run([docker, "port", name, "5432/tcp"], env, capture=True).stdout.strip().splitlines()[0]
    if not port.startswith("127.0.0.1:"):
        raise RuntimeError("Test database must be loopback-only.")
    return f"postgresql://geofathom:{password}@{port}/geofathom"


def wait_postgis(dsn):
    import psycopg
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                version = conn.execute("SELECT postgis_version()").fetchone()[0]
                print("PostGIS:", version, flush=True)
                return
        except psycopg.Error:
            time.sleep(1)
    raise RuntimeError("PostGIS did not become ready within 90 seconds.")


def check_junit(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if not totals["tests"] or any(totals[k] for k in ("failures", "errors", "skipped")):
        raise RuntimeError(f"Full Windows acceptance requires no skipped or failed tests: {totals}")
    return totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--soak-seconds", type=int, default=60)
    parser.add_argument("--docker", help="Absolute docker.exe path if it is not on PATH")
    parser.add_argument("--reuse-test-postgis", action="store_true",
                        help="Use the explicitly configured disposable GEOFATHOM_TEST_POSTGIS_DSN")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--baseline", type=Path, help="Previous host acceptance report directory")
    parser.add_argument("--resume", type=Path,
                        help="Reuse hash-verified native checkpoints from a compatible run")
    parser.add_argument("--max-regression-percent", type=float, default=15)
    args = parser.parse_args()
    if not 0 <= args.max_regression_percent <= 50:
        parser.error("Performance regression tolerance must be 0–50 percent.")
    if sys.platform != "win32" or not 5 <= args.soak_seconds <= 86400:
        parser.error("Windows acceptance requires 5–86400 soak seconds.")
    for name in ("git", "cmake", "ctest", "nvidia-smi"):
        require(name)
    if not args.skip_web:
        require("node")
        require("npm.cmd")
        require("npx.cmd")
    docker = None if args.reuse_test_postgis else require("docker", args.docker)
    original = os.environ.copy()
    # Start clean rather than inherit deployment or previous test policies.
    env = {k: v for k, v in original.items() if not k.startswith("GEOFATHOM_")}
    # Ambient test filters, coverage files and provider keys may silently
    # invalidate isolation or cause live external API calls during acceptance.
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "COVERAGE_FILE",
                "COVERAGE_PROCESS_START", "COVERAGE_RCFILE", "GROQ_API_KEY",
                "GEMINI_API_KEY", "OPENAI_API_KEY", "CI"):
        env.pop(key, None)
    if original.get("GEOFATHOM_CUDA_BIN"):
        env["GEOFATHOM_CUDA_BIN"] = original["GEOFATHOM_CUDA_BIN"]
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["GEOFATHOM_SKIP_DOTENV"] = "1"
    env.update(GEOFATHOM_REQUIRE_NATIVE="1", GEOFATHOM_SPECTRAL_DEVICE="cpu",
               GEOFATHOM_VISION_DEVICE="cpu", GEOFATHOM_VISION_DEVICE_POSTPROCESS="0",
               GEOFATHOM_VISION_IO_BINDING="0", GEOFATHOM_AUTH_MODE="local")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    out = ROOT / "build" / "host-acceptance" / stamp
    out.mkdir(parents=True)
    env.update(GEOFATHOM_DATABASE_PATH=str(out / "workspace.sqlite"),
               GEOFATHOM_IMAGERY_DIR=str(out / "imagery"),
               GEOFATHOM_VERSION_DIR=str(out / "versions"),
               GEOFATHOM_VISION_MODELS_DIR=str(out / "models"))
    report = {"passed": False, "soak_seconds_per_device": args.soak_seconds,
              "web_requested": not args.skip_web, "stages": []}
    name = "geofathom-acceptance-" + stamp.lower()
    state = {"container_started": False}
    python = sys.executable
    try:
        # External CTest executables also require the CUDA runtime on PATH.
        toolkit_bin = run([python, "-c",
            "from core.cuda_environment import cuda_bin_directory; print(cuda_bin_directory() or '')"],
            env, capture=True).stdout.strip()
        if not toolkit_bin:
            raise RuntimeError("CUDA toolkit runtime was not found; configure CUDA_PATH.")
        env["PATH"] = toolkit_bin + os.pathsep + env["PATH"]
        env["GEOFATHOM_CUDA_BIN"] = toolkit_bin
        if not shutil.which("nvcc", path=env["PATH"]):
            raise RuntimeError("CUDA compiler nvcc is not available on the configured PATH.")
        report["git_commit"] = run(["git", "rev-parse", "HEAD"], env, capture=True).stdout.strip()
        report["tracked_tree_dirty"] = bool(run(["git", "status", "--porcelain", "--untracked-files=all"],
            env, capture=True).stdout.strip())
        report["platform"] = platform.platform()
        report["cpu"] = platform.processor()
        report["logical_cpu_count"] = os.cpu_count()
        report["python_version"] = platform.python_version()
        report["package_versions"] = {}
        for package in ("numpy", "rasterio", "onnx", "onnxruntime-gpu", "psycopg", "pytest", "coverage"):
            try:
                report["package_versions"][package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                report["package_versions"][package] = None
        for module in ("pytest", "pytest_cov", "onnx", "onnxruntime", "psycopg"):
            run([python, "-c", f"import {module}"], env)
        gpu = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], env, capture=True).stdout
        if "4070 Ti SUPER" not in gpu:
            raise RuntimeError("Expected RTX 4070 Ti SUPER was not detected.")
        report["gpu"] = gpu.strip()
        report["toolchain"]={
            "nvcc":run(["nvcc","--version"],env,capture=True).stdout.strip(),
            "cmake":run(["cmake","--version"],env,capture=True).stdout.strip(),
            "driver":run(["nvidia-smi","--query-gpu=driver_version","--format=csv,noheader"],env,capture=True).stdout.strip(),
        }
        previous=args.resume.resolve(strict=True) if args.resume else None
        prior=json.loads((previous/"acceptance.json").read_text(encoding="utf-8")) if previous else None
        if prior is not None:
            verify_resume_metadata(prior,report)
            report["resume_from"]=str(previous)
        for device in ("cpu","cuda"):
            native_stage(device,out,env,report,args.soak_seconds,previous,prior)
        run([python, "scripts/acceptance_model.py", "--directory", out / "models",
             "--output", out / "strict-gpu.json"], env)
        benchmark_env = {**env, "GEOFATHOM_VISION_DEVICE_POSTPROCESS": "1",
                         "GEOFATHOM_VISION_IO_BINDING": "1"}
        run([python, "benchmarks/gpu_acceptance.py", "--model", "gpu_acceptance",
             "--runs", "100", "--output", out / "gpu-inference.json"], benchmark_env)
        json.loads((out / "gpu-inference.json").read_text(encoding="utf-8"))
        report["stages"].append("Strict synthetic ONNX GPU inference")
        if args.baseline:
            from quality_report import compare_performance
            report["performance_comparison"] = compare_performance(
                args.baseline, out, report, args.max_regression_percent)
            if not report["performance_comparison"]["passed"]:
                raise RuntimeError("Hardware performance regressed beyond the configured tolerance.")
        dsn = original.get("GEOFATHOM_TEST_POSTGIS_DSN") if args.reuse_test_postgis else start_postgis(docker, name, env, state)
        if not dsn:
            raise RuntimeError("A disposable test DSN must be explicitly configured.")
        wait_postgis(dsn)
        env.update(GEOFATHOM_TEST_POSTGIS_DSN=dsn, GEOFATHOM_STRESS_8K="1",
                   GEOFATHOM_STRESS_16K="1", GEOFATHOM_STRESS_MILLION_SEGMENTS="1",
                   GEOFATHOM_REQUIRE_REAL_ONNX="1", GEOFATHOM_GPU_ACCEPTANCE_MODEL="gpu_acceptance")
        junit = out / "pytest.xml"
        env["COVERAGE_FILE"] = str(out / ".coverage")
        run([python, "scripts/run_acceptance.py", "-q", "-rs", "--tb=short", "--cov", "--cov-branch",
             f"--cov-report=html:{out / 'coverage'}", f"--cov-report=xml:{out / 'coverage.xml'}",
             f"--cov-report=json:{out / 'coverage.json'}",
             "--cov-report=term-missing", f"--junitxml={junit}"], env)
        report["pytest"] = check_junit(junit)
        from quality_report import python_coverage
        report["python_coverage"] = python_coverage(out / "coverage.json")
        report["stages"].append("All Python tests with live PostGIS")
        if not args.skip_web:
            # Do not reuse a running application or enable CI retries on the host.
            web_env = {**env, "GEOFATHOM_E2E_FRESH": "1", "GEOFATHOM_E2E_DATABASE_PATH": str(out / "e2e.sqlite")}
            web_env.pop("CI", None)
            for key in ("GEOFATHOM_TEST_POSTGIS_DSN", "GEOFATHOM_GPU_ACCEPTANCE_MODEL"):
                web_env.pop(key, None)
            for command in (["npm.cmd", "ci", "--no-audit", "--no-fund"],
                            ["npm.cmd", "run", "build"], ["npm.cmd", "run", "test:coverage"],
                            ["npx.cmd", "playwright", "install", "chromium"],
                            ["npm.cmd", "run", "test:e2e:coverage"],
                            ["npm.cmd", "run", "coverage:merge"]):
                run(command, web_env, ROOT / "web")
            from quality_report import frontend_coverage
            shutil.copytree(ROOT / "web" / "coverage", out / "web-coverage")
            report["web_coverage"] = frontend_coverage(out / "web-coverage" / "coverage-summary.json")
            report["stages"].append("Web build, unit and browser E2E")
        report["passed"] = True
        report["scope"] = "backend-and-hardware" if args.skip_web else "backend-hardware-and-web"
        # Synthetic model and single-host tests are not full production qualification.
        report["production_qualified"] = False
    except Exception as error:
        # Keep a durable report on failure without exposing database credentials.
        report["failure_type"] = type(error).__name__
        raise
    finally:
        if state["container_started"]:
            try:
                run([docker, "stop", name], env)
            except subprocess.CalledProcessError:
                report["passed"] = False
                report["cleanup_failed"] = True
        save_report(out,report)
        print("Report:", out / "acceptance.json", flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
