"""Project-scoped sample revisions and preflight against actual managed features."""
from fastapi import APIRouter,Request,Header,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .remote_samples import SampleSet,save,read,revisions,materialize,preflight
from .remote_model_managed import ModelBand,TrainingParameters
from .remote_managed import DiskQuality
from storage.database import StorageError
from .routes import require_raster_import

router=APIRouter(prefix='/projects',tags=['remote-sensing-samples'])

class Check(BaseModel):
    model_config=ConfigDict(extra='forbid')
    features:dict[str,ModelBand]=Field(min_length=1,max_length=16)
    quality:list[DiskQuality]=Field(default_factory=list,max_length=16)
    parameters:TrainingParameters=Field(default_factory=TrainingParameters)


def failure(e):return HTTPException(status_code=404 if isinstance(e,(StorageError,FileNotFoundError)) and 'not found' in str(e).lower() else 422,detail=str(e))


@router.get('/{project_id}/remote-samples')
def list_revisions(project_id:str):
    try:return {'revisions':revisions(project_id)}
    except (ValueError,OSError) as e:raise failure(e) from e


@router.post('/{project_id}/remote-samples',status_code=201)
def save_revision(project_id:str,body:SampleSet,request:Request,token:str|None=Header(default=None,alias='X-GeoFathom-Admin-Token')):
    require_raster_import(request,token)
    try:return save(project_id,body)
    except (ValueError,OSError) as e:raise failure(e) from e


@router.get('/{project_id}/remote-samples/{uid}')
def get_revision(project_id:str,uid:str):
    try:return read(project_id,uid)
    except (ValueError,OSError) as e:raise failure(e) from e


@router.post('/{project_id}/remote-samples/{uid}/labels')
def prepare_labels(project_id:str,uid:str,request:Request,token:str|None=Header(default=None,alias='X-GeoFathom-Admin-Token')):
    require_raster_import(request,token)
    try:return materialize(project_id,uid)
    except (ValueError,OSError) as e:raise failure(e) from e


@router.post('/{project_id}/remote-samples/{uid}/preflight')
def check_samples(project_id:str,uid:str,body:Check,request:Request,token:str|None=Header(default=None,alias='X-GeoFathom-Admin-Token')):
    from .store import image_file
    require_raster_import(request,token)
    try:
        revision=read(project_id,uid)
        def spec(b):
            d=b.model_dump(mode='json');d['path']=str(image_file(d.pop('image_id')));return d
        result=preflight(SampleSet.model_validate(revision['body']),{r:spec(b) for r,b in body.features.items()},[spec(q) for q in body.quality],body.parameters.model_dump())
        result['revision_sha256']=revision['sha256'];result['source_sha256']={next(uid for uid in ({str(b.image_id) for b in [*body.features.values(),*body.quality]}|{revision['body']['target_image_id']}) if str(image_file(uid))==p):h for p,h in result['source_sha256'].items()}
        return result
    except (ValueError,OSError) as e:raise failure(e) from e
