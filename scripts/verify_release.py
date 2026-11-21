"""Independently verify release bundles against their contents and hash manifest."""
from hashlib import sha256
import json
from pathlib import Path,PurePosixPath
from zipfile import ZipFile

def verify(archive):
    archive=Path(archive)
    sidecar=archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()
    if sidecar!=[sha256(archive.read_bytes()).hexdigest(),archive.name]:
        raise RuntimeError("Release archive SHA-256 mismatch.")
    with ZipFile(archive) as bundle:
        names=bundle.namelist()
        if len(names)!=len(set(names)) or any(PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts or "\\" in name for name in names):
            raise RuntimeError("Unsafe release archive path.")
        manifest=json.loads(bundle.read("SHA256.json"))
        if set(manifest)!=set(names)-{"SHA256.json"}:
            raise RuntimeError("Release archive manifest mismatch.")
        for name,digest in manifest.items():
            if sha256(bundle.read(name)).hexdigest()!=digest:
                raise RuntimeError("Release payload corruption.")
        if (not any(n.endswith(".whl") for n in names)
            or not any(n.endswith((".dll",".so",".dylib")) for n in names)
            or "web/index.html" not in names):
            raise RuntimeError("Release bundle is missing required components.")
    return len(names)

if __name__=="__main__":
    paths=list(Path("release-dist").glob("*.zip"))
    if not paths:raise RuntimeError("No release bundles found.")
    for path in paths:print(path,verify(path),"verified files")
