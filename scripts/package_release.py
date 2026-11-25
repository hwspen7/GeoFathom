"""Package CPU-native binary, wheel and built UI; include file SHA-256 manifest."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parents[1]
out=root/"release-dist";out.mkdir(exist_ok=True)
stage=root/"build"/"release-stage"
if stage.exists():shutil.rmtree(stage)
stage.mkdir(parents=True)
subprocess.run([sys.executable,"-m","pip","wheel",str(root),"--no-deps",
                "-w",str(stage)],check=True)
names={"Windows":"geofathom_native.dll","Linux":"libgeofathom_native.so",
       "Darwin":"libgeofathom_native.dylib"}
native=list((root/"build"/"native").rglob(names[platform.system()]))
if not native:
    raise RuntimeError("Compiled native library is missing.")
shutil.copy2(native[0],stage/native[0].name)
shutil.copytree(root/"web"/"dist",stage/"web")
manifest={}
for path in sorted(stage.rglob("*")):
    if path.is_file():
        manifest[path.relative_to(stage).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
(stage/"SHA256.json").write_text(json.dumps(manifest,indent=2),encoding="utf8")
archive=out/("GeoFathom-"+platform.system()+"-"+platform.machine()+".zip")
with ZipFile(archive,"w",compression=ZIP_DEFLATED) as z:
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            z.write(path,path.relative_to(stage).as_posix())
(archive.with_suffix(".zip.sha256")).write_text(
    hashlib.sha256(archive.read_bytes()).hexdigest()+"  "+archive.name+"\n",encoding="ascii")
