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
