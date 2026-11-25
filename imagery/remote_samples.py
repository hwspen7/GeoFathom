"""Reviewed scientific sample revisions, explicit splits and spatial preflight."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID,uuid4

import numpy as np
from pydantic import BaseModel,ConfigDict,Field
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from scipy.spatial import cKDTree
from shapely.geometry import shape

from analysis.science_raster import require
from storage.database import _connect,get_project,StorageError,_now
from .remote_partitions import sample_partitions
from .remote_model import Inputs
from .remote_windowed import digest,windows


class ClassDefinition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:int=Field(gt=0,le=65535)
    name:str=Field(min_length=1,max_length=100)
    description:str=Field(default='',max_length=2000)


class Annotation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    geometry:dict
    class_id:int=Field(gt=0,le=65535)
    split:Literal['train','reference']='train'
    review:Literal['pending','accepted','rejected']='pending'
    source:str=Field(min_length=10,max_length=2000)
    reviewer:str=Field(default='',max_length=200)


class SampleSet(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=150)
    target_image_id:UUID
    classes:list[ClassDefinition]=Field(min_length=2,max_length=32)
    annotations:list[Annotation]=Field(min_length=1,max_length=1000)
    training_reference_buffer_m:float=Field(default=1000,ge=0,le=100000)


def canonical(body):return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def table(db):
    db.execute('CREATE TABLE IF NOT EXISTS remote_sample_revisions (id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,created_at TEXT NOT NULL,sha256 TEXT NOT NULL,body TEXT NOT NULL)')


def save(project_id,body):
    get_project(project_id);body=SampleSet.model_validate(body);validate_geometry(body)
    data=body.model_dump(mode='json');uid=str(uuid4());checksum=canonical(data);created=_now()
    with _connect() as db:
        table(db);db.execute('INSERT INTO remote_sample_revisions VALUES (?,?,?,?,?)',(uid,project_id,created,checksum,json.dumps(data,allow_nan=False)))
    return {'id':uid,'sha256':checksum,'created_at':created,'body':data}


def read(project_id,uid):
    get_project(project_id)
    with _connect() as db:
        table(db);row=db.execute('SELECT * FROM remote_sample_revisions WHERE id=? AND project_id=?',(uid,project_id)).fetchone()
    if row is None:raise StorageError('Sample revision not found.')
    return {'id':row['id'],'sha256':row['sha256'],'created_at':row['created_at'],'body':json.loads(row['body'])}


def revisions(project_id):
    get_project(project_id)
    with _connect() as db:
        table(db);rows=db.execute('SELECT id,created_at,sha256,body FROM remote_sample_revisions WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(project_id,)).fetchall()
    return [{'id':r['id'],'created_at':r['created_at'],'sha256':r['sha256'],'name':json.loads(r['body'])['name']} for r in rows]


def validate_geometry(body):
    classes=[c.id for c in body.classes];require(len(set(classes))==len(classes),'Class identities must be unique.')
    require(len({a.id for a in body.annotations})==len(body.annotations),'Sample identities must be unique.')
    for a in body.annotations:
        require(a.class_id in classes,'Annotation class is absent from the codebook.')
        require(len(json.dumps(a.geometry))<=64000,'Annotation geometry exceeds the vertex budget.')
        geometry=shape(a.geometry);require(not geometry.is_empty and geometry.is_valid and geometry.geom_type in ('Point','Polygon','MultiPolygon'),'Use valid WGS84 point or polygon samples.')
        xmin,ymin,xmax,ymax=geometry.bounds
        require(-180<=xmin<=xmax<=180 and -90<=ymin<=ymax<=90,'Sample coordinates must be WGS84 longitude/latitude.')
        if a.review=='accepted':require(bool(a.reviewer.strip()),'Accepted samples require a reviewer identity.')


def raster_samples(body,target):
    validate_geometry(body)
    require(target.crs and target.crs.is_projected and target.crs.linear_units in ('metre','meter') and target.width*target.height<=2_000_000,'Sample preparation requires a projected metre grid of at most two million cells.')
    require(target.transform.a>0 and target.transform.e<0 and target.transform.b==target.transform.d==0,'Use a north-up sample grid.')
    labels={name:np.zeros(target.shape,dtype=np.int32) for name in ('train','reference')};occupied=np.zeros(target.shape,bool);details=[]
    for a in body.annotations:
        if a.review!='accepted':continue
        geometry=transform_geom('EPSG:4326',target.crs,a.geometry)
        mask=rasterize([(geometry,1)],out_shape=target.shape,transform=target.transform,dtype='uint8').astype(bool)
        require(mask.any(),'An accepted sample contains no target cell centers: '+a.id)
        require(not np.any(mask&occupied),'Accepted sample geometries overlap on target cells: '+a.id)
        occupied|=mask;labels[a.split][mask]=a.class_id;details.append({'id':a.id,'split':a.split,'cells':int(mask.sum())})
    for split,z in labels.items():require(np.count_nonzero(z)<=10000,'Each sample split is limited to 10,000 explicit cells; refine polygons instead of silent subsampling.')
    require(np.count_nonzero(labels['train'])>=40,'Use at least forty accepted training cells.')
    rr,cc=np.nonzero(labels['train']);x,y=rasterio.transform.xy(target.transform,rr,cc)
    tr=cKDTree(np.column_stack((x,y)));rr,cc=np.nonzero(labels['reference'])
    if len(rr):
        x,y=rasterio.transform.xy(target.transform,rr,cc);distance,_=tr.query(np.column_stack((x,y)),p=np.inf)
        require(np.all(distance>body.training_reference_buffer_m+1e-8),'Reference samples violate the declared training exclusion buffer.')
    return labels,details


def preflight(body,features,quality,parameters):
    from .remote_model_managed import TrainingParameters
    parameters=TrainingParameters.model_validate(parameters).model_dump()
    from .store import image_file
    from .remote_windowed import same_grid
    target_path=image_file(str(body.target_image_id));target_hash=digest(target_path)
    with ExitStack() as stack:
        inputs=Inputs(stack,features,quality);target=stack.enter_context(rasterio.open(target_path))
        require(same_grid(inputs.grid,target),'Sample target and feature grids must match exactly.')
        labels,details=raster_samples(body,inputs.grid)
        y=labels['train'];complete=np.zeros(y.shape,bool)
        for window in windows(inputs.grid.width,inputs.grid.height,256):
            values=inputs.read(window);r,c=int(window.row_off),int(window.col_off)
            complete[r:r+int(window.height),c:c+int(window.width)]=np.isfinite(values).all(axis=0)
        selected=(y>0)&complete;rr,cc=np.nonzero(selected);values=y[selected]
        require(len(rr)>=40,'Fewer than forty reviewed training cells survive feature/QA screening.')
        folds,excluded=sample_partitions(rr,cc,inputs.grid.transform,parameters['block_m'],parameters['folds'],parameters['buffer_blocks'])
        classes=[c.id for c in body.classes];fold_rows=[]
        for j in range(parameters['folds']):
            hold=folds==j;training=~excluded[j];calibration=(folds==(j+1)%parameters['folds'])&training
            inner=training&~excluded[(j+1)%parameters['folds']]
            counts=[{'class':c,'fit':int(np.sum(training&(values==c))),'holdout':int(np.sum(hold&(values==c))),
                     'calibration':int(np.sum(calibration&(values==c))),'inner_fit':int(np.sum(inner&(values==c)))} for c in classes]
            ready=all(c['fit']>=5 and c['holdout']>=1 and (not parameters['calibrate'] or c['inner_fit']>=5 and c['calibration']>=1) for c in counts)
            fold_rows.append({'fold':j,'ready':ready,'classes':counts})
        inputs.unchanged();require(digest(target_path)==target_hash,'Sample target changed during preflight.')
        inputs.hashes[str(target_path)]=target_hash
        return {'ready':all(r['ready'] for r in fold_rows),'training_cells':len(rr),'qa_excluded_training_cells':int(np.count_nonzero(y)-len(rr)),
            'class_support':{str(c):int(np.sum(values==c)) for c in classes},'folds':fold_rows,'annotations':details,
            'review_counts':{state:sum(a.review==state for a in body.annotations) for state in ('pending','accepted','rejected')},
            'reference_cells':int(np.count_nonzero(labels['reference'])),'parameters':parameters,'source_sha256':inputs.hashes}


def materialize(project_id,uid):
    from .store import image_file,store_upload
    revision=read(project_id,uid);body=SampleSet.model_validate(revision['body']);path=image_file(str(body.target_image_id));source_hash=digest(path)
    with rasterio.open(path) as target:
        labels,details=raster_samples(body,target);profile=dict(driver='GTiff',width=target.width,height=target.height,count=1,dtype='int32',nodata=0,crs=target.crs,transform=target.transform,compress='deflate')
    results={}
    with TemporaryDirectory(prefix='sample-labels-') as folder:
        try:
            for split,z in labels.items():
                if not np.any(z):continue
                output=Path(folder)/(split+'.tif')
                with rasterio.open(output,'w',**profile) as dst:
                    dst.write(z,1);dst.update_tags(TERRAIN_UNIT='class',SAMPLE_SPLIT=split,SAMPLE_REVISION_SHA256=revision['sha256'],CLASS_CODEBOOK=json.dumps([c.model_dump() for c in body.classes]))
                require(digest(path)==source_hash,'Sample grid changed during preparation.')
                results[split]=store_upload(output,body.name+' '+split+'.tif',json.dumps({'sample_revision_sha256':revision['sha256'],'split':split,'target_sha256':source_hash,'annotations':details}))
        except BaseException:
            for result in results.values():
                p=image_file(result['id']);p.unlink(missing_ok=True);p.with_suffix('.json').unlink(missing_ok=True)
            raise
    return {'revision_sha256':revision['sha256'],'rasters':results}
