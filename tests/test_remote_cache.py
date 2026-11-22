from pathlib import Path
import httpx
import pytest
from imagery.remote_cache import download_asset
from imagery.remote import provider_config,vetted_asset_href

HOST="e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"
URL="https://"+HOST+"/tiles/example.tif"

def test_resume_range_and_content_address(tmp_path):
    calls=[]
    etag='"stable-version"'
    data=b"abcdefgh"
    def handler(request):
        if request.method=="HEAD":
            return httpx.Response(200,headers={"etag":etag,"content-length":str(len(data))})
        calls.append(request.headers.get("range"))
        assert request.headers.get("if-range")==etag
        return httpx.Response(206,headers={"etag":etag,"content-range":"bytes 4-7/8"},content=data[4:])
    from hashlib import sha256
    key=sha256((URL+"\n"+etag).encode()).hexdigest()
    (tmp_path/(key+".part")).write_bytes(data[:4])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=download_asset(URL,tmp_path,client)
        assert result.read_bytes()==data
        assert download_asset(URL,tmp_path,client)==result
    assert calls==["bytes=4-"]
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*.lock"))

def test_operator_defined_provider_has_separate_asset_allowlist(monkeypatch):
    import json
    monkeypatch.setenv("GEOFATHOM_STAC_PROVIDERS",json.dumps({"other":{
        "url":"https://catalog.example.test/v1","collections":["s2"],
        "hosts":["assets.example.test"],"assets":{"nir":"B08","red":"B04","scl":"QA"}}}))
    config=provider_config("other")
    assert config["assets"]["nir"]=="B08"
    assert vetted_asset_href("https://assets.example.test/x.tif",config["hosts"])
    with pytest.raises(ValueError):
        vetted_asset_href("https://"+HOST+"/x.tif",config["hosts"])
    with pytest.raises(ValueError):
        provider_config("unknown")


def cache_key(etag='"stable"'):
    from hashlib import sha256
    return sha256((URL+"\n"+etag).encode()).hexdigest()


@pytest.mark.parametrize("headers",[
    {"etag":'W/"weak"',"content-length":"8"},
    {"etag":'"stable"',"content-length":"0"},
    {"etag":'"stable"',"content-length":"9999999999999"},
    {"etag":"","content-length":"8"},
])
def test_invalid_head_never_downloads(tmp_path,headers):
    def handler(request):
        assert request.method=="HEAD"
        return httpx.Response(200,headers=headers)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError,match="strong ETag"):
            download_asset(URL,tmp_path,client)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mode,expected",[
    ("changed","changed during transfer"),
    ("encoded","Encoded COG"),
    ("range","unexpected byte range"),
    ("status","unsupported range"),
    ("oversized","exceeded"),
    ("short","Incomplete COG"),
])
def test_transfer_failure_does_not_publish_cache(tmp_path,mode,expected):
    tag='"stable"'
    key=cache_key(tag)
    partial=tmp_path/(key+".part")
    partial.write_bytes(b"abcd")
    def handler(request):
        if request.method=="HEAD":
            return httpx.Response(200,headers={"etag":tag,"content-length":"8"})
        assert request.headers["if-match"]==tag
        assert request.headers["range"]=="bytes=4-"
        if mode=="changed":
            return httpx.Response(206,headers={"etag":'"changed"'},content=b"efgh")
        if mode=="encoded":
            return httpx.Response(206,headers={"etag":tag,"content-encoding":"gzip"})
        if mode=="range":
            return httpx.Response(206,headers={"etag":tag,"content-range":"bytes 0-3/8"},content=b"efgh")
        if mode=="status":
            return httpx.Response(204,headers={"etag":tag})
        return httpx.Response(206,headers={"etag":tag,"content-range":"bytes 4-7/8"},
            content=b"efghx" if mode=="oversized" else b"ef")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError,match=expected):
            download_asset(URL,tmp_path,client)
    assert not (tmp_path/(key+".tif")).exists()
    assert not (tmp_path/(key+".sha256")).exists()
    assert not (tmp_path/(key+".lock")).exists()
    if mode=="changed":assert not partial.exists()
    if mode=="oversized":assert partial.stat().st_size==0
    if mode=="short":assert partial.read_bytes()==b"abcdef"


@pytest.mark.parametrize("damage",["oversized-partial","corrupt-final","invalid-tag","ignored-range"])
def test_corrupt_or_outdated_cache_is_replaced(tmp_path,damage):
    key=cache_key()
    data=b"abcdefgh"
    if damage=="oversized-partial":
        (tmp_path/(key+".part")).write_bytes(b"invalid-long-prefix")
    elif damage in ("corrupt-final","invalid-tag"):
        (tmp_path/(key+".tif")).write_bytes(b"incorrect" if damage=="corrupt-final" else data)
        (tmp_path/(key+".sha256")).write_bytes(b"bad" if damage=="corrupt-final" else b"\xff")
    else:
        (tmp_path/(key+".part")).write_bytes(b"abcd")
    calls=[]
    def handler(request):
        if request.method=="HEAD":
            return httpx.Response(200,headers={"etag":'"stable"',"content-length":"8"})
        calls.append(request.headers.get("range"))
        return httpx.Response(200,headers={"etag":'"stable"'},content=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=download_asset(URL,tmp_path,client)
        assert result.read_bytes()==data
        assert download_asset(URL,tmp_path,client)==result
    assert calls==["bytes=4-" if damage=="ignored-range" else None]
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.lock"))


def test_download_lock_and_insufficient_disk_preserve_existing_data(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from imagery import remote_cache
    key=cache_key()
    lock=tmp_path/(key+".lock")
    lock.touch()
    def handler(request):
        assert request.method=="HEAD"
        return httpx.Response(200,headers={"etag":'"stable"',"content-length":"8"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError,match="already downloading"):
            download_asset(URL,tmp_path,client)
        assert lock.exists()
        lock.unlink()
        partial=tmp_path/(key+".part")
        partial.write_bytes(b"abcd")
        monkeypatch.setattr(remote_cache.shutil,"disk_usage",lambda _:SimpleNamespace(free=0))
        with pytest.raises(RuntimeError,match="Insufficient disk"):
            download_asset(URL,tmp_path,client)
        assert partial.read_bytes()==b"abcd" and not lock.exists()
