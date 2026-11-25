"""Fixed-support model ablations and portable, hash-verified experiment archives."""
import argparse
from contextlib import ExitStack
import csv
import io
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import zipfile

import numpy as np
from pydantic import BaseModel,ConfigDict,Field
import rasterio

from analysis.science_raster import require
from .remote_model import Inputs,train,classification_metrics
from .remote_model_managed import TrainInput,snapshot_config
from .remote_confidence import probability_scores
from .remote_partitions import sample_partitions
from .remote_windowed import digest,windows


class Variant(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=100)
    roles:list[str]=Field(min_length=1,max_length=16)
    trees:int=Field(default=64,ge=16,le=128)
    max_depth:int=Field(default=12,ge=2,le=16)
    min_leaf:int=Field(default=2,ge=1,le=100)
    seed:int=Field(default=42,ge=0,le=2147483647)


class ExperimentInput(TrainInput):
    variants:list[Variant]=Field(min_length=1,max_length=12)
    archive_mb:int=Field(default=2048,ge=128,le=16384)


def validate(payload):
    body=ExperimentInput.model_validate(payload)
    require(len({v.name for v in body.variants})==len(body.variants),'Experiment names must be unique.')
    for v in body.variants:
        require(set(v.roles)<=set(body.features) and len(set(v.roles))==len(v.roles),'Variants require unique bound feature roles.')
    return body


def experiment_path(job_id):
    from .remote_managed import result_path
    return result_path(job_id).with_suffix('.experiment.zip')


def write_member(archive,name,path,check):
    info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
    with archive.open(info,'w',force_zip64=True) as out,Path(path).open('rb') as source:
        while chunk:=source.read(1024*1024):check();out.write(chunk)


def run_experiment(config,output,progress=None,check=lambda:None):
    from jobs.reproducibility import canonical_hash,software_record
    output=Path(output).resolve();require(output.parent.is_dir() and not output.exists(),'Choose a new experiment archive.')
    variants=[Variant.model_validate(v) for v in config['variants']]
    require(1<=len(variants)<=12 and len({v.name for v in variants})==len(variants),'Use 1–12 uniquely named variants.')
    for v in variants:require(set(v.roles)<=set(config['features']) and len(set(v.roles))==len(v.roles),'Unknown or repeated variant feature.')
    budget=config.get('archive_mb',2048)*1024**2
    require(128*1024**2<=budget<=16384*1024**2,'Invalid archive budget.')
    with TemporaryDirectory(prefix='.experiment-'+output.stem+'-',dir=output.parent) as folder,ExitStack() as stack:
        folder=Path(folder);inputs=Inputs(stack,config['features'],config.get('quality',[]),config['labels']);grid=inputs.grid
        require(grid.crs.is_projected and grid.crs.linear_units in ('metre','meter'),'Experiments require a projected metre grid.')
        path_names={path:'inputs/'+str(i)+'.tif' for i,path in enumerate(sorted(inputs.hashes))}
        stable_names={path:config.get('source_names',{}).get(path,name) for path,name in path_names.items()}
        size=sum(Path(p).stat().st_size for p in inputs.hashes)
        require(size+len(variants)*64*1024**2+grid.width*grid.height*8<=budget and 2*budget<shutil.disk_usage(folder).free,'Experiment archive or scratch disk budget exceeded.')
        ds,b,q,_=inputs.labels
        require(ds.tags().get('SAMPLE_SPLIT')!='reference','Reference-only samples cannot select experiment models.')
        common=folder/'common-labels.tif';count=original=0;rrs=[];ccs=[];truth=[]
        with rasterio.open(common,'w',driver='GTiff',height=grid.height,width=grid.width,count=1,dtype='float64',crs=grid.crs,transform=grid.transform,nodata=np.nan,compress='deflate') as dst:
            dst.update_tags(**ds.tags())
            for window in windows(grid.width,grid.height,config.get('tile',256)):
                from .remote_band import read_calibrated
                check();labels=read_calibrated(ds,b,q,window)[0];selected=np.isfinite(labels)&(labels>0);original+=int(selected.sum())
                require(original<=10000,'Experiments accept at most 10,000 explicit original labeled cells.')
                good=selected&np.isfinite(inputs.read(window)).all(axis=0);labels[~good]=np.nan;dst.write(labels,1,window=window)
                rr,cc=np.nonzero(good);rrs.extend((rr+int(window.row_off)).tolist());ccs.extend((cc+int(window.col_off)).tolist());truth.extend(labels[good].astype(int).tolist());count+=len(rr)
        require(count>=40,'Insufficient common feature support for an experiment.')
        order=np.lexsort((ccs,rrs));rr=np.asarray(rrs)[order];cc=np.asarray(ccs)[order];truth=np.asarray(truth)[order];classes=np.unique(truth)
        from .remote_model_managed import TrainingParameters
        p=TrainingParameters.model_validate(config.get('parameters',{})).model_dump()
        folds,excluded=sample_partitions(rr,cc,grid.transform,p['block_m'],p['folds'],p['buffer_blocks'])
        partition=canonical_hash({'rows':rr.tolist(),'cols':cc.tolist(),'labels':truth.tolist(),'folds':folds.tolist(),'excluded':[z.tolist() for z in excluded]})
        baseline=np.zeros((len(truth),len(classes)));baseline_rows=[]
        for j in range(p['folds']):
            fit=~excluded[j];hold=folds==j;frequencies=np.array([np.count_nonzero(fit&(truth==c)) for c in classes],float)
            require(np.all(frequencies>=5),'Prior baseline needs five fit samples of every class in every spatial fold.')
            baseline[hold]=frequencies/frequencies.sum()
            baseline_rows.append({'fold':j,'accuracy':float(np.mean(classes[np.argmax(baseline[hold],axis=1)]==truth[hold]))})
        prior={**classification_metrics(truth,classes[np.argmax(baseline,axis=1)],classes),**probability_scores(baseline,truth,classes),'folds':baseline_rows}
        records=[];files={'common-labels.tif':common}
        for i,v in enumerate(variants):
            check()
            # The same QA intersection was already applied to all feature roles.
            local={**config,'labels':{'path':str(common)},'features':{r:config['features'][r] for r in v.roles},'quality':[],
                'source_names':{**stable_names,str(common):'common_support_labels'},
                'parameters':{**p,**v.model_dump(exclude={'name','roles'})}}
            path=folder/('model-'+str(i)+'.json')
            result=train(local,path,(lambda f:progress((i+f)/len(variants)*.8)) if progress else None,check)
            artifact=json.loads(path.read_text());sites=artifact['training_samples']
            require(sites['rows']==rr.tolist() and sites['cols']==cc.tolist(),'A variant changed the common sample support.')
            name='models/model-'+str(i)+'.json';files[name]=path
            records.append({'name':v.name,'parameters':local['parameters'],'roles':v.roles,'model_member':name,'model_sha256':result['sha256'],
                'partition_sha256':partition,'validation':result['validation'],
                'delta_accuracy_vs_prior':result['validation']['overall_accuracy']-prior['overall_accuracy']})
        inputs.unchanged();check()
        # Every archived input is named independently of local filesystem locations.
        files.update({name:Path(path) for path,name in path_names.items()})
        def replace_spec(spec):return {**spec,'path':path_names[str(Path(spec['path']).resolve())]}
        portable={k:config[k] for k in ('parameters','variants','tile','archive_mb') if k in config}
        portable.update(features={r:replace_spec(b) for r,b in config['features'].items()},quality=[replace_spec(q) for q in config.get('quality',[])],labels=replace_spec(config['labels']))
        portable['source_names']={name:stable_names[path] for path,name in path_names.items()}
        csv_buffer=io.StringIO();writer=csv.writer(csv_buffer);writer.writerow(['variant','accuracy','macro_f1','mean_iou','log_loss','brier','sample_cells'])
        for name,m in [('Spatial prior baseline',prior),*[(r['name'],r['validation']) for r in records]]:
            writer.writerow([name,m['overall_accuracy'],m['macro_f1'],m['mean_iou'],m['log_loss'],m['multiclass_brier'],m['cells']])
        comparison=csv_buffer.getvalue();table_path=folder/'comparison.csv';table_path.write_text(comparison);files['comparison.csv']=table_path
        manifest={'schema':'geofathom-remote-experiment-1','configuration':portable,'software':software_record(),
            'partition_sha256':partition,'common_training_cells':count,'excluded_incomplete_cells':original-count,
            'baseline':prior,'variants':records,'files':{name:digest(path) for name,path in files.items()},
            'scope':'Same explicit labels, common feature/QA support and buffered spatial folds. Model selection and ablations are exploratory OOF comparisons; final independent-site evaluation is still required.'}
        staged=folder/'experiment.zip'
        with zipfile.ZipFile(staged,'w') as archive:
            for name,path in files.items():check();write_member(archive,name,path,check)
            info=zipfile.ZipInfo('manifest.json',date_time=(1980,1,1,0,0,0));archive.writestr(info,json.dumps(manifest,sort_keys=True,allow_nan=False))
        require(staged.stat().st_size<=budget,'Experiment archive exceeds its declared budget.')
        inputs.unchanged();check();os.link(staged,output)
        return {'schema':manifest['schema'],'sha256':digest(output),'source_sha256':{stable_names[p]:h for p,h in inputs.hashes.items()},
            'common_training_cells':count,'excluded_incomplete_cells':original-count,'partition_sha256':partition,'baseline':prior,'variants':records,'comparison_csv':comparison,'scope':manifest['scope']}


def run_managed(payload,job_id,progress,check):
    body=validate(payload);output=experiment_path(job_id)
    with snapshot_config(body,job_id,check) as (config,folder):
        config.update(variants=[v.model_dump() for v in body.variants],archive_mb=body.archive_mb)
        try:return run_experiment(config,output,progress,check)
        except BaseException:output.unlink(missing_ok=True);raise


def restore(archive_path,directory):
    """Verify every member before exposing a runnable, relative-path configuration."""
    directory=Path(directory).resolve();require(not directory.exists(),'Choose a new archive restore directory.')
    with zipfile.ZipFile(archive_path) as archive:
        items=archive.infolist();names=[i.filename for i in items]
        require(len(items)<=128 and len(names)==len(set(names)) and 'manifest.json' in names,'Invalid or oversized experiment manifest.')
        require(sum(i.file_size for i in items)<=16*1024**3 and archive.getinfo('manifest.json').file_size<=16*1024**2,'Archive restore budget exceeded.')
        for i in items:
            p=Path(i.filename);require(not p.is_absolute() and p.as_posix()==i.filename and '..' not in p.parts and '\\' not in i.filename and not i.is_dir() and ((i.external_attr>>16)&0o170000)!=0o120000,'Unsafe archive member.')
        manifest=json.loads(archive.read('manifest.json'));require(manifest.get('schema')=='geofathom-remote-experiment-1','Unsupported experiment archive.')
        require(set(manifest['files'])==set(names)-{'manifest.json'},'Archive file manifest mismatch.')
        try:
            directory.mkdir()
            for i in items:
                target=directory/i.filename;target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(i) as source,target.open('wb') as out:shutil.copyfileobj(source,out,1024*1024)
                if i.filename!='manifest.json':require(digest(target)==manifest['files'][i.filename],'Experiment member checksum mismatch.')
            config=manifest['configuration']
            for spec in [*config['features'].values(),*config.get('quality',[]),config['labels']]:
                require(spec['path'] in manifest['files'] and spec['path'].startswith('inputs/'),'Configuration references an undeclared input.')
                spec['path']=str(directory/spec['path'])
            config['source_names']={str(directory/k):v for k,v in config.get('source_names',{}).items()}
            return config,manifest
        except BaseException:shutil.rmtree(directory,ignore_errors=True);raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('restore_directory',type=Path);parser.add_argument('--rerun',type=Path);parser.add_argument('--allow-software-change',action='store_true');args=parser.parse_args()
    config,manifest=restore(args.archive,args.restore_directory)
    if args.rerun:
        from jobs.reproducibility import compatible,software_record
        require(args.allow_software_change or compatible(manifest['software'],software_record()),'Archived scientific software differs; explicitly accept software changes before rerunning.')
        result=run_experiment(config,args.rerun)
    else:result={'verified':True,'files':len(manifest['files']),'partition_sha256':manifest['partition_sha256']}
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
