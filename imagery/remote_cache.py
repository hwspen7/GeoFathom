"""Optional resumable cache for operator-approved immutable HTTP COG assets."""
from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
import httpx

def _sha(path):
    digest=sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()

def download_asset(href,root,client=None,allowed_hosts=None):
    # The caller cannot bypass the remote catalog's HTTPS allowlist.
    from .remote import vetted_asset_href
    vetted_asset_href(href,allowed_hosts)
    if client is None:
        with httpx.Client(timeout=30,follow_redirects=False) as http:
            return download_asset(href,root,http,allowed_hosts)
    headers={"Accept-Encoding":"identity"}
    head=client.head(href,headers=headers,follow_redirects=False)
    head.raise_for_status()
    etag=head.headers.get("etag","")
    length=int(head.headers.get("content-length","0"))
    maximum=int(os.getenv("GEOFATHOM_REMOTE_ASSET_MAX_MB","2048"))*1024*1024
    if (not 1<=maximum<=8*1024**3 or not 0<length<=maximum or
        not re.fullmatch(r'"[^"\r\n]{1,200}"',etag)):
        raise ValueError("COG cache requires a bounded size and strong ETag.")
    key=sha256((href+"\n"+etag).encode()).hexdigest()
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    final=root/(key+".tif");partial=root/(key+".part");tag=root/(key+".sha256")
    lock=root/(key+".lock")
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as error:
        raise RuntimeError("COG asset is already downloading; retry later.") from error
    os.close(fd)
    try:
        if final.is_file() and tag.is_file():
            try:
                expected=tag.read_text(encoding="ascii").strip()
            except UnicodeError:
                expected=""
            if final.stat().st_size==length and _sha(final)==expected:
                return final
            final.unlink(missing_ok=True);tag.unlink(missing_ok=True)
        start=partial.stat().st_size if partial.exists() else 0
        if start>length:
            partial.unlink();start=0
        if shutil.disk_usage(root).free<length-start+16*1024*1024:
            raise RuntimeError("Insufficient disk capacity for remote asset.")
        if start<length:
            # Require the same strong entity tag even on a full download.
            requested={**headers,"If-Match":etag}
            if start:
                requested.update({"Range":f"bytes={start}-","If-Range":etag})
            with client.stream("GET",href,headers=requested,follow_redirects=False) as response:
                response.raise_for_status()
                if response.headers.get("etag")!=etag:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError("Remote COG changed during transfer.")
                if response.headers.get("content-encoding","identity")!="identity":
                    raise RuntimeError("Encoded COG responses cannot be resumed safely.")
                if start and response.status_code==206:
                    if response.headers.get("content-range")!=f"bytes {start}-{length-1}/{length}":
                        raise RuntimeError("Remote COG returned an unexpected byte range.")
                    mode="ab"
                elif response.status_code==200:
                    start=0;mode="wb"
                else:
                    raise RuntimeError("Remote COG returned an unsupported range response.")
                with partial.open(mode) as output:
                    total=start
                    for chunk in response.iter_bytes(1024*1024):
                        total+=len(chunk)
                        if total>length:
                            # Do not preserve a complete-looking prefix from
                            # an invalid oversized transfer for later reuse.
                            output.truncate(0)
                            raise RuntimeError("Remote COG exceeded its advertised size.")
                        output.write(chunk)
        if partial.stat().st_size!=length:
            raise RuntimeError("Incomplete COG transfer; retry to resume.")
        digest=_sha(partial)
        os.replace(partial,final)
        tag.write_text(digest,encoding="ascii")
        return final
    finally:
        lock.unlink(missing_ok=True)
