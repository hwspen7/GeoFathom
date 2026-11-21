from hashlib import sha256
import json
from zipfile import ZipFile
import pytest
from scripts.verify_release import verify

def test_release_verification_rejects_corrupted_payload_and_archive(tmp_path):
    p=tmp_path/"bundle.zip"
    contents={"app.whl":b"wheel","native.dll":b"native","web/index.html":b"web"}
    manifest={name:sha256(data).hexdigest() for name,data in contents.items()}
    def pack():
        with ZipFile(p,"w") as z:
            for name,data in contents.items():z.writestr(name,data)
            z.writestr("SHA256.json",json.dumps(manifest))
        p.with_suffix(".zip.sha256").write_text(sha256(p.read_bytes()).hexdigest()+"  "+p.name)
    pack()
    assert verify(p)==4
    contents["native.dll"]=b"corrupt"
    pack()
    with pytest.raises(RuntimeError,match="payload"):
        verify(p)
    p.write_bytes(b"changed")
    with pytest.raises(RuntimeError,match="SHA-256"):
        verify(p)
