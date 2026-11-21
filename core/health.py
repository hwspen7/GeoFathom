"""Dependency-aware readiness check distinct from inexpensive liveness."""
import shutil
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from storage.database import _connect,database_path

router=APIRouter(tags=["health"])

@router.get("/health/ready")
def readiness():
    state={"database":False,"scratch":False}
    try:
        with _connect() as db:
            state["database"]=db.execute("SELECT 1").fetchone()[0]==1
    except Exception:
        pass
    try:
        path=database_path()
        path.parent.mkdir(parents=True,exist_ok=True)
        state["scratch"]=shutil.disk_usage(path.parent).free>32*1024*1024
    except Exception:
        pass
    okay=all(state.values())
    return JSONResponse(status_code=200 if okay else 503,
        content={"status":"ready" if okay else "unavailable","checks":state})
