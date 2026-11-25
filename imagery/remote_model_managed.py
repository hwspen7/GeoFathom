"""Operator-scoped portable model training and prediction jobs."""
from contextlib import contextmanager
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from analysis.science_raster import require
from storage.snapshots import copy_verified
from .remote_managed import DiskBand, DiskQuality, result_path
from .remote_semantics import FeatureQuantity


class ModelBand(DiskBand):
    quantity: FeatureQuantity='reflectance'


class TrainingParameters(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    calibrate:bool=False
    trees:int=Field(default=64,ge=16,le=128)
    max_depth:int=Field(default=12,ge=2,le=16)
    min_leaf:int=Field(default=2,ge=1,le=100)
    seed:int=Field(default=42,ge=0,le=2147483647)
    block_m:float=Field(default=1000,ge=1,le=100000)
    folds:int=Field(default=5,ge=3,le=10)
    buffer_blocks:int=Field(default=1,ge=0,le=1)


class PredictInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    model_job_id:UUID
    features:dict[str,ModelBand]=Field(min_length=1,max_length=16)
    quality:list[DiskQuality]=Field(default_factory=list,max_length=16)
    maximum_training_distance:float|None=Field(default=None,gt=0,le=1000000)
    minimum_probability:float=Field(default=0,ge=0,le=1)
    tile:int=Field(default=256,ge=32,le=512)
    snapshot_mb:int=Field(default=1024,ge=64,le=8192)


class TrainInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    features:dict[str,ModelBand]=Field(min_length=1,max_length=16)
    labels:DiskBand
    quality:list[DiskQuality]=Field(default_factory=list,max_length=16)
    parameters:TrainingParameters=Field(default_factory=TrainingParameters)
    tile:int=Field(default=256,ge=32,le=512)
    snapshot_mb:int=Field(default=1024,ge=64,le=8192)


class EvaluationInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    prediction_job_id:UUID
    reference_image_id:UUID
    reference_band:int=Field(default=1,ge=1,le=1024)
    reference_description:str=Field(min_length=10,max_length=4000)
    block_m:float=Field(default=1000,ge=1,le=100000)
    training_buffer_m:float=Field(default=1000,ge=0,le=100000)
    replicates:int=Field(default=500,ge=100,le=2000)
    seed:int=Field(default=42,ge=0,le=2147483647)
    tile:int=Field(default=256,ge=32,le=512)
    snapshot_mb:int=Field(default=1024,ge=64,le=8192)


def model_path(job_id):return result_path(job_id).with_suffix('.model.json')


def validate(payload,training):
    body=(TrainInput if training else PredictInput).model_validate(payload)
    require(all(set(q.roles)<=set(body.features) for q in body.quality),'Unknown model QA target role.')
    return body


@contextmanager
def snapshot_config(body,job_id,check):
    from .store import image_file
    items=[*body.features.values(),*body.quality]
    if isinstance(body,TrainInput):items.append(body.labels)
    ids=sorted({str(b.image_id) for b in items});originals={uid:image_file(uid) for uid in ids}
    size=sum(p.stat().st_size for p in originals.values());root=result_path(job_id).parent;root.mkdir(parents=True,exist_ok=True)
    require(size<=body.snapshot_mb*1024**2 and size+64*1024**2<shutil.disk_usage(root).free,'Model snapshot disk budget exceeded.')
    with TemporaryDirectory(prefix='model-input-'+str(job_id)+'-',dir=root) as folder:
        paths={}
        for uid,source in originals.items():
            check();target=Path(folder)/(uid+'.tif');copy_verified(source,target);paths[uid]=str(target)
        def spec(item):
            data=item.model_dump(mode='json');data['path']=paths[data.pop('image_id')];return data
        config={'features':{r:spec(b) for r,b in body.features.items()},'quality':[spec(q) for q in body.quality],
                'tile':body.tile,'source_names':{p:uid for uid,p in paths.items()}}
        if isinstance(body,TrainInput):config.update(labels=spec(body.labels),parameters=body.parameters.model_dump())
        else:config.update(minimum_probability=body.minimum_probability,maximum_training_distance=body.maximum_training_distance)
        yield config,Path(folder)


def run_managed(payload,job_id,project_id,training,progress,check):
    from .remote_model import train,predict
    from .remote_windowed import digest
    body=validate(payload,training);output=model_path(job_id) if training else result_path(job_id)
    with snapshot_config(body,job_id,check) as (config,folder):
        if not training:
            from jobs.queue import get_job
            job=get_job(project_id,str(body.model_job_id))
            require(job['kind']=='remote_model_train' and job['status']=='completed','Choose a completed model from this project.')
            source=model_path(body.model_job_id);target=folder/'model.json'
            require(digest(source)==job['result']['sha256'],'Trained model changed or is corrupt.')
            copy_verified(source,target);config['model_path']=str(target)
        try:
            receipt=(train if training else predict)(config,output,progress,check);check();return receipt
        except BaseException:
            output.unlink(missing_ok=True)
            raise


def run_evaluation(payload,job_id,project_id,progress,check):
    from jobs.queue import get_job
    from .store import image_file
    from .remote_windowed import digest
    from .remote_model_validation import evaluate
    body=EvaluationInput.model_validate(payload)
    prediction=get_job(project_id,str(body.prediction_job_id))
    require(prediction['kind']=='remote_model_predict' and prediction['status']=='completed','Choose completed predictions from this project.')
    model_id=prediction['payload']['model_job_id'];model=get_job(project_id,model_id)
    sources={'prediction:'+prediction['id']:result_path(prediction['id']),
        'model:'+model_id:model_path(model_id),str(body.reference_image_id):image_file(str(body.reference_image_id))}
    require(digest(sources['prediction:'+prediction['id']])==prediction['result']['sha256'],'Prediction changed or is corrupt.')
    require(digest(sources['model:'+model_id])==prediction['result']['model_sha256']==model['result']['sha256'],'Model identity changed.')
    size=sum(p.stat().st_size for p in sources.values());output=result_path(job_id);output.parent.mkdir(parents=True,exist_ok=True)
    require(size<=body.snapshot_mb*1024**2 and size+64*1024**2<shutil.disk_usage(output.parent).free,'Evaluation snapshot disk budget exceeded.')
    with TemporaryDirectory(prefix='evaluation-input-'+str(job_id)+'-',dir=output.parent) as folder:
        paths={}
        for i,(uid,p) in enumerate(sources.items()):
            check();target=Path(folder)/(str(i)+p.suffix);copy_verified(p,target);paths[uid]=str(target)
        config={**body.model_dump(exclude={'prediction_job_id','reference_image_id','snapshot_mb'}),
            'model_path':paths['model:'+model_id],'prediction_path':paths['prediction:'+prediction['id']],
            'reference_path':paths[str(body.reference_image_id)],'source_names':{p:uid for uid,p in paths.items()}}
        try:
            receipt=evaluate(config,output,progress,check);check();return receipt
        except BaseException:
            output.unlink(missing_ok=True)
            raise
