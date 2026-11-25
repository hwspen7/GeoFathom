"""Disk optical jobs for managed imagery IDs, never user-supplied server paths."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
import rasterio
from .remote_catalog import BY_ID,WINDOWED_IDS,windowed_roles
from .remote_windowed import process
from analysis.science_raster import require
from storage.snapshots import copy_verified
from .remote_semantics import TimeContext

class DiskBand(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    image_id:UUID
    band:int=Field(default=1,ge=1,le=1024)
    encoding:Literal['metadata','raw','landsat_sr','landsat_st','custom']='metadata'
    unit:str=Field(default='',max_length=80)
    scale:float=Field(default=1,gt=0,le=1e12)
    offset:float=Field(default=0,ge=-1e12,le=1e12)

class DiskQuality(BaseModel):
    model_config=ConfigDict(extra='forbid')
    image_id:UUID
    band:int=Field(default=1,ge=1,le=1024)
    scheme:Literal['binary','sentinel_clear','landsat_clear','landsat_unsaturated']='binary'
    roles:list[str]=Field(default_factory=list,max_length=64)

class DiskInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    operation:str=Field(max_length=80)
    bindings:dict[str,DiskBand]=Field(min_length=1,max_length=64)
    quality:list[DiskQuality]=Field(default_factory=list,max_length=64)
    times:list[float]=Field(default_factory=list,max_length=64)
    time_context:TimeContext|None=None
    parameters:dict[str,float]=Field(default_factory=dict,max_length=12)
    tile:int=Field(default=512,ge=64,le=1024)

def result_path(job_id):
    from storage.database import database_path
    uid=str(UUID(str(job_id)))
    root=database_path().with_suffix('.remote-results')
    return root/(uid+'.tif')

def validate(body):
    p=DiskInput.model_validate(body);m=BY_ID.get(p.operation)
    require(p.operation in WINDOWED_IDS,'Operation is not certified for finite-neighborhood disk processing.')
    require(set(p.bindings)=={r for r,_ in windowed_roles(p.operation,p.times)},'Bind every required role.')
    return p

def run_managed(payload,job_id,progress,check):
    from .store import image_file
    p=validate(payload);output=result_path(job_id);output.parent.mkdir(parents=True,exist_ok=True)
    items=[*p.bindings.values(),*p.quality];ids=sorted(set(str(x.image_id) for x in items))
    originals={uid:image_file(uid) for uid in ids}
    require(sum(x.stat().st_size for x in originals.values())<=512*1024*1024,'Managed disk input snapshot exceeds 512 MB.')
    for path in originals.values():
        with rasterio.open(path) as ds:require(ds.width*ds.height<=25_000_000,'Managed disk job is limited to 25 million cells per band.')
    with TemporaryDirectory(prefix='remote-input-',dir=output.parent) as folder:
        snapshots={};hashes={}
        for uid,path in originals.items():
            check();target=Path(folder)/(uid+'.tif');hashes[uid]=copy_verified(path,target);snapshots[uid]=str(target)
        def spec(item):
            q=item.model_dump(mode='json');uid=q.pop('image_id');q['path']=snapshots[uid];return q
        def tick(fraction):
            progress(fraction);check()
        result=process(p.operation,{role:spec(b) for role,b in p.bindings.items()},output,p.parameters,
                       [spec(q) for q in p.quality],p.tile,progress=tick,times=p.times,
                       time_context=p.time_context.model_dump(mode='json') if p.time_context else None)
        for role,entry in result['bands'].items():
            uid=str(p.bindings[role].image_id);require(entry['sha256']==hashes[uid],'Snapshot hash changed.')
            entry.pop('path',None);entry['image_id']=uid
        for entry,q in zip(result['quality_masks'],p.quality):
            uid=str(q.image_id);require(entry['sha256']==hashes[uid],'Quality snapshot hash changed.');entry.pop('path',None);entry['image_id']=uid
        try:check()
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        return result
