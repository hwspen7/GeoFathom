"""Content-addressed, operator-managed archive for immutable analysis inputs.

The archive may be on a shared filesystem. Only immutable blobs are shared;
the project SQLite database never needs to be mounted by a compute node.
Operators provision storage quotas and backup/garbage collection separately.
"""
from hashlib import sha256
from pathlib import Path
import os
import re
from tempfile import TemporaryDirectory
from .snapshots import copy_verified

_DIGEST=re.compile(r"^[a-f0-9]{64}$")

def object_path(root,digest):
    if not isinstance(digest,str) or not _DIGEST.fullmatch(digest):
        raise ValueError("Invalid content address.")
    return Path(root).resolve()/digest[:2]/digest

def _digest(path):
    result=sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            result.update(block)
    return result.hexdigest()

def publish(root,source,digest):
    target=object_path(root,digest)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if target.is_symlink() or _digest(target)!=digest:
            raise RuntimeError("Archived input does not match its content address.")
        return target
    with TemporaryDirectory(prefix=".publish-",dir=target.parent) as tmp:
        stage=Path(tmp)/"blob"
        if copy_verified(source,stage)!=digest:
            raise RuntimeError("Input differs from its execution snapshot.")
        # Publish using exclusive atomic hard-link creation on the same
        # filesystem. A concurrent writer of the same content is harmless.
        try:
            os.link(stage,target)
        except FileExistsError:
            pass
        if target.is_symlink() or _digest(target)!=digest:
            raise RuntimeError("Published archive object failed verification.")
    return target

def materialize(root,digest,destination):
    source=object_path(root,digest)
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("Archived input is missing or invalid.")
    if copy_verified(source,Path(destination))!=digest:
        Path(destination).unlink(missing_ok=True)
        raise RuntimeError("Archived input failed SHA-256 verification.")

def archive_inputs(root,provenance):
    from imagery.store import image_file
    from vision.semantic import model_directory
    for uid,digest in provenance["source_sha256"].items():
        publish(root,image_file(uid),digest)
    for name,digest in provenance["model_files_sha256"].items():
        if Path(name).name!=name:
            raise ValueError("Invalid model archive filename.")
        publish(root,model_directory()/name,digest)
