"""Scientific job recipes bound to actual input hashes and execution software."""
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import os
from pathlib import Path
import platform

from analysis.science_raster import require

SCIENTIFIC_KINDS={'remote_windowed','remote_cube','remote_model_train','remote_model_predict','remote_model_evaluate','remote_experiment'}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def source_fingerprint():
    root=Path(__file__).resolve().parents[1];digest=hashlib.sha256()
    files=[]
    for directory in ('imagery','analysis','terrain','vision','geometry','jobs','core','storage','requirements'):
        files.extend(p for p in (root/directory).rglob('*') if p.is_file() and p.suffix in ('.py','.cpp','.h','.lock'))
    files.append(root/'pyproject.toml')
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode());digest.update(b'\0')
        digest.update(path.read_bytes());digest.update(b'\0')
    return digest.hexdigest()


def software_record():
    from terrain.research import software_revision
    import rasterio
    packages={}
    for name in ('numpy','scipy','rasterio','scikit-learn','pyproj','numba'):
        try:packages[name]=version(name)
        except PackageNotFoundError:packages[name]=None
    record={'source_tree_sha256':source_fingerprint(),'python':platform.python_version(),
        'platform':platform.system(),'packages':packages,'gdal':rasterio.__gdal_version__,
        'thread_configuration':{n:os.getenv(n) for n in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS')}}
    record.update(software_revision())
    return record


def compatible(first,second,check_threads=True):
    keys=('source_tree_sha256','python','platform','packages','gdal')+ (('thread_configuration',) if check_threads else ())
    return all(first.get(k)==second.get(k) for k in keys)


def result_inputs(kind,payload,result):
    if kind=='remote_windowed':
        inputs={item['image_id']:item['sha256'] for item in result['bands'].values()}
        inputs.update({item['image_id']:item['sha256'] for item in result.get('quality_masks',[])})
    else:inputs=dict(result['source_sha256'])
    if kind=='remote_model_predict':inputs['model:'+payload['model_job_id']]=result['model_sha256']
    return inputs


def recorded_execute(kind,payload,execute):
    replay=payload.get('_reproduction')
    clean={k:v for k,v in payload.items() if k!='_reproduction'}
    software=software_record()
    if replay:
        require(replay.get('allow_software_change') or compatible(replay['software'],software),
                'Scientific software changed; repeat requires explicit acceptance of the current algorithm version.')
    result=execute(clean)
    inputs=result_inputs(kind,clean,result)
    if replay:require(inputs==replay['input_sha256'],'Scientific inputs changed; the saved experiment was not reproduced.')
    require(source_fingerprint()==software['source_tree_sha256'],'Scientific source changed while the job was running.')
    result['reproducibility']={'schema':'geofathom-scientific-execution-1','kind':kind,
        'request_sha256':canonical_hash(clean),'input_sha256':inputs,'software':software,
        'output_sha256':result['sha256'],'repeated_from_job':replay['job_id'] if replay else None,
        'software_changed':bool(replay and not compatible(replay['software'],software))}
    return result


def recipe(project_id,job_id):
    from .queue import get_job
    job=get_job(project_id,job_id)
    require(job['kind'] in SCIENTIFIC_KINDS and job['status']=='completed','A completed scientific job is required.')
    evidence=job['result'].get('reproducibility')
    require(evidence is not None,'This historical job has no verified execution recipe.')
    payload={k:v for k,v in job['payload'].items() if k!='_reproduction'}
    require(canonical_hash(payload)==evidence['request_sha256'],'Recorded job parameters changed.')
    result={'schema':'geofathom-scientific-recipe-1','job_id':job_id,'project_id':project_id,
        'kind':job['kind'],'payload':payload,**evidence}
    result['schema']='geofathom-scientific-recipe-1'
    result['recipe_sha256']=canonical_hash(result)
    return result


def repeat(project_id,job_id,allow_software_change=False):
    from .queue import get_job,queue_job
    from imagery.store import image_file
    from imagery.remote_managed import result_path
    from imagery.remote_model_managed import model_path
    from imagery.remote_windowed import digest
    original=recipe(project_id,job_id)
    require(allow_software_change or compatible(original['software'],software_record(),check_threads=False),
            'Scientific software changed; explicitly allow the current algorithm version to repeat.')
    # Check before scheduling and check the execution snapshots again afterward.
    for key,expected in original['input_sha256'].items():
        if ':' in key:
            prefix,uid=key.split(':',1);dependency=get_job(project_id,uid)
            require(dependency['status']=='completed','A required scientific dependency is incomplete.')
            if prefix=='model':
                require(dependency['kind']=='remote_model_train','Wrong saved model dependency.')
                path=model_path(uid)
            else:
                require(prefix=='prediction' and dependency['kind']=='remote_model_predict','Wrong prediction dependency.')
                path=result_path(uid)
        else:path=image_file(key)
        require(digest(path)==expected,'Scientific input checksum changed; restore the original input before repeating.')
    return queue_job(project_id,original['kind'],original['payload'],reproduction={
        'job_id':job_id,'software':original['software'],'input_sha256':original['input_sha256'],
        'allow_software_change':allow_software_change})
