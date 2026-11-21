from concurrent.futures import ThreadPoolExecutor
from imagery.cache import ByteCache,file_identity

def test_lru_byte_limits_and_eviction():
    cache=ByteCache(8)
    assert cache.get("a",lambda:b"aaaa")==b"aaaa"
    assert cache.get("b",lambda:b"bbbb")==b"bbbb"
    assert cache.get("a",lambda:b"wrong")==b"aaaa"
    cache.get("c",lambda:b"cccc")
    assert cache.stats()["entries"]==2
    assert cache.stats()["bytes"]==8
    assert cache.get("b",lambda:b"B")==b"B"
    assert cache.get("large",lambda:b"x"*20)==b"x"*20
    assert cache.stats()["bytes"]<=8

def test_concurrent_cache_respects_bound_and_file_version(tmp_path):
    cache=ByteCache(128)
    def task(i):
        return cache.get(i%20,lambda:bytes([i%20])*32)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs=list(pool.map(task,range(200)))
    assert all(data==bytes([i%20])*32 for i,data in enumerate(outputs))
    assert cache.stats()["bytes"]<=128
    path=tmp_path/"file"
    path.write_bytes(b"a")
    first=file_identity(path)
    path.write_bytes(b"bb")
    assert file_identity(path)!=first
