"""Start the local API and Vite together, ensuring readiness before opening the UI."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parents[1]

def ready(url):
    try:
        with urllib.request.urlopen(url,timeout=1) as response:
            return response.status==200
    except OSError:
        return False

def wait(process,url,seconds=60):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited with code {process.returncode}: {url}")
        if ready(url):return
        time.sleep(.25)
    raise RuntimeError(f"Service did not become ready: {url}")

def main():
    npm=shutil.which("npm.cmd" if os.name=="nt" else "npm")
    if not npm:raise SystemExit("Install Node.js and make npm available on PATH.")
    if not (ROOT/"web"/"node_modules"/"vite").exists():
        subprocess.run([npm,"ci","--no-audit","--no-fund"],cwd=ROOT/"web",check=True)
    children=[]
    try:
        if ready("http://127.0.0.1:8000/health/ready"):
            raise RuntimeError("Port 8000 already serves an API. Stop the old server before launching this revision.")
        api=subprocess.Popen([sys.executable,"-m","uvicorn","core.main:app","--host","127.0.0.1","--port","8000"],cwd=ROOT)
        children.append(api)
        wait(api,"http://127.0.0.1:8000/health/ready")
        front=subprocess.Popen([npm,"run","dev","--","--host","127.0.0.1"],cwd=ROOT/"web",
            env={**os.environ,"VITE_API_URL":"/api"})
        children.append(front)
        wait(front,"http://127.0.0.1:5173/api/health/ready")
        print("GeoFathom ready: http://127.0.0.1:5173",flush=True)
        webbrowser.open("http://127.0.0.1:5173")
        while all(p.poll() is None for p in children):time.sleep(.5)
        raise RuntimeError("A GeoFathom service stopped.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(children):
            if process.poll() is None:
                if os.name=="nt":
                    subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:process.terminate()
        for process in children:
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()

if __name__=="__main__":main()
