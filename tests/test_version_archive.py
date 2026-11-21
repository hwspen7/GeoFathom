from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import pytest
from storage.versions import publish,materialize,object_path

def test_content_address_retains_old_revision_and_rejects_corruption(tmp_path):
    root=tmp_path/"versions";source=tmp_path/"source"
    source.write_bytes(b"old")
    old=sha256(b"old").hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths=list(pool.map(lambda _:publish(root,source,old),range(8)))
    assert len(set(paths))==1
    source.write_bytes(b"new")
    new=sha256(b"new").hexdigest()
    publish(root,source,new)
    output=tmp_path/"recovered"
    materialize(root,old,output)
    assert output.read_bytes()==b"old"
    object_path(root,old).write_bytes(b"corrupt")
    with pytest.raises(RuntimeError,match="verification"):
        materialize(root,old,tmp_path/"corrupt")
    assert not (tmp_path/"corrupt").exists()
    with pytest.raises(ValueError):
        object_path(root,"../../etc/passwd")
