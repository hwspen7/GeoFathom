"""Independent-reference classification diagnostics with spatial cluster intervals."""
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine
from scipy.spatial import cKDTree

from analysis.science_raster import require
from .remote_windowed import digest,same_grid,windows


def scores(matrix):
    """Metrics from a reference-row confusion matrix, also used by bootstrap."""
    diagonal=np.diag(matrix);reference=matrix.sum(axis=1);prediction=matrix.sum(axis=0)
    f1=np.divide(2*diagonal,reference+prediction,out=np.zeros(len(diagonal)),where=reference+prediction>0)
    union=reference+prediction-diagonal
    iou=np.divide(diagonal,union,out=np.zeros(len(diagonal)),where=union>0)
    return [float(diagonal.sum()/matrix.sum()),float(f1.mean()),float(iou[union>0].mean())]


def block_intervals(matrices,replicates,seed,check=lambda:None):
    matrices=np.asarray(matrices);n=len(matrices)
    require(8<=n<=2000,'Accuracy intervals require 8–2,000 occupied spatial blocks.')
    require(type(replicates) is int and 100<=replicates<=2000,'Use 100–2,000 block bootstrap replicates.')
    require(n*replicates*matrices.shape[1]**2<=50_000_000,'Spatial interval work budget exceeded.')
    rng=np.random.default_rng(seed);draws=[]
    for _ in range(replicates):
        check();weights=np.bincount(rng.integers(0,n,size=n),minlength=n)
        draws.append(scores(np.einsum('b,bij->ij',weights,matrices)))
    intervals=np.quantile(draws,[.025,.975],axis=0)
    return {name:intervals[:,i].tolist() for i,name in enumerate(('overall_accuracy','macro_f1','mean_iou'))}


def evaluate(config,output,progress=None,check=lambda:None):
    model_path=Path(config['model_path']);prediction_path=Path(config['prediction_path']);reference_path=Path(config['reference_path'])
    require(model_path.stat().st_size<=64*1024**2,'Model exceeds 64 MiB.')
    model=json.loads(model_path.read_text());classes=np.asarray(model['classes']);k=len(classes)
    require(model.get('schema')=='geofathom-random-forest-1' and 2<=k<=32 and np.all(np.diff(classes)>0),'Use a saved scientific forest.')
    hashes={str(p.resolve()):digest(p) for p in (model_path,prediction_path,reference_path)}
    require(digest(reference_path)!=model['training_label_sha256'],'Independent-reference evaluation cannot reuse the training label file.')
    require(len(config.get('reference_description','').strip())>=10,'Describe the independent reference source and labeling procedure.')
    block_m=config.get('block_m',1000.);buffer_m=config.get('training_buffer_m',block_m)
    require(np.isfinite(block_m) and 1<=block_m<=100000 and np.isfinite(buffer_m) and 0<=buffer_m<=100000,'Invalid evaluation block or exclusion distance.')
    output=Path(output).resolve();require(not output.exists() and output.parent.is_dir(),'Choose a new error raster output.')
    tile=config.get('tile',256);require(type(tile) is int and 32<=tile<=512,'Evaluation tile must be 32–512.')
    reference_band=config.get('reference_band',1);staged=None
    with rasterio.open(prediction_path) as prediction,rasterio.open(reference_path) as reference:
        require(same_grid(prediction,reference),'Explicitly align independent labels to the prediction grid.')
        require(prediction.crs.is_projected and prediction.crs.linear_units in ('metre','meter'),'Spatial accuracy requires a projected metre grid.')
        require(prediction.width*prediction.height<=150_000_000 and prediction.count==k+4 and 1<=reference_band<=reference.count,'Invalid prediction/reference dimensions.')
        require(prediction.tags().get('MODEL_SHA256')==digest(model_path),'Prediction and saved model hashes differ.')
        require(reference.scales[reference_band-1]==1 and reference.offsets[reference_band-1]==0,'Reference class codes cannot have radiometric scaling.')
        training=model['training_grid'];a=Affine(*training['transform']);rr=np.asarray(model['training_samples']['rows']);cc=np.asarray(model['training_samples']['cols'])
        x=a.c+(cc+.5)*a.a;y=a.f+(rr+.5)*a.e
        tx,ty=Transformer.from_crs(training['crs'],prediction.crs,always_xy=True).transform(x,y)
        require(np.isfinite(tx).all() and np.isfinite(ty).all(),'Training geometry cannot be transformed into the evaluation CRS.')
        tree=cKDTree(np.column_stack((tx,ty)))
        blocks={};matrix=np.zeros((k,k),dtype=np.int64);bins=np.zeros((10,3));brier=loss=0.
        total_reference=excluded=paired=unclassified=0;total_windows=((prediction.width+tile-1)//tile)*((prediction.height+tile-1)//tile)
        try:
            fd,name=tempfile.mkstemp(prefix='.evaluation-'+output.stem+'-',suffix='.tif',dir=output.parent);os.close(fd);staged=Path(name)
            with rasterio.open(staged,'w',driver='GTiff',width=prediction.width,height=prediction.height,count=1,dtype='float64',
                crs=prediction.crs,transform=prediction.transform,nodata=np.nan,compress='deflate',tiled=True,blockxsize=256,blockysize=256) as dst:
                dst.update_tags(TERRAIN_UNIT='class',REMOTE_METHOD='independent_reference_error')
                for n,window in enumerate(windows(prediction.width,prediction.height,tile)):
                    check();truth=reference.read(reference_band,window=window,masked=True).astype(float).filled(np.nan)
                    require(not np.isinf(truth).any(),'Infinite reference class codes are invalid.')
                    valid=np.isfinite(truth)&(truth>0)
                    require(np.all(truth[valid]==np.floor(truth[valid])) and np.isin(truth[valid],classes).all(),'Reference contains unsupported or noninteger class codes.')
                    total_reference+=int(valid.sum());row,col=np.indices(truth.shape)
                    xx=prediction.transform.c+(col+window.col_off+.5)*prediction.transform.a
                    yy=prediction.transform.f+(row+window.row_off+.5)*prediction.transform.e
                    if valid.any():
                        distance,_=tree.query(np.column_stack((xx[valid],yy[valid])),p=np.inf)
                        keep=distance>buffer_m+1e-8;excluded+=int((~keep).sum());valid[valid]=keep
                    label=prediction.read(1,window=window,masked=True).astype(float).filled(np.nan)
                    probability=prediction.read(list(range(5,k+5)),window=window,masked=True).filled(np.nan)
                    good=valid&np.isfinite(label)&np.isfinite(probability).all(axis=0)
                    unclassified+=int((valid&~good).sum());error=np.full(truth.shape,np.nan)
                    if good.any():
                        require(np.isin(label[good],classes).all(),'Prediction contains unknown class IDs.')
                        prob=probability[:,good].T
                        require(np.all((prob>=0)&(prob<=1)) and np.allclose(prob.sum(axis=1),1,atol=1e-8),'Invalid probability bands.')
                        ti=np.searchsorted(classes,truth[good]);pi=np.searchsorted(classes,label[good]);code=ti*k+pi
                        local=np.bincount(code,minlength=k*k).reshape(k,k);matrix+=local;paired+=len(code)
                        keys,ids=np.unique(np.column_stack((np.floor(xx[good]/block_m),np.floor(yy[good]/block_m))).astype(np.int64),axis=0,return_inverse=True)
                        for j,key in enumerate(keys):
                            key=tuple(key);value=np.bincount(code[ids==j],minlength=k*k).reshape(k,k)
                            blocks[key]=blocks.get(key,np.zeros((k,k),dtype=np.int64))+value
                        require(len(blocks)<=2000,'Too many evaluation blocks; increase block width.')
                        correct=ti==pi;error[good]=(~correct).astype(float)
                        confidence=prob.max(axis=1);bucket=np.minimum((confidence*10).astype(int),9)
                        for j in range(10):
                            m=bucket==j;bins[j]+=[int(m.sum()),float(confidence[m].sum()),int(correct[m].sum())]
                        one=np.eye(k)[ti];brier+=float(np.sum((prob-one)**2));loss-=float(np.log(np.clip(prob[np.arange(len(ti)),ti],1e-15,1)).sum())
                    dst.write(error,1,window=window)
                    if progress:progress(.7*(n+1)/total_windows)
            require(paired>0,'No independent classified reference observations remain after training exclusion.')
            replicates=config.get('replicates',500);seed=config.get('seed',42)
            intervals=block_intervals([blocks[key] for key in sorted(blocks)],replicates,seed,check)
            # Convert aggregate confusion counts into the same class metrics used for OOF.
            reference_counts=matrix.sum(axis=1);prediction_counts=matrix.sum(axis=0);diagonal=np.diag(matrix)
            precision=np.divide(diagonal,prediction_counts,out=np.zeros(k),where=prediction_counts>0)
            recall=np.divide(diagonal,reference_counts,out=np.zeros(k),where=reference_counts>0)
            union=reference_counts+prediction_counts-diagonal
            iou=np.divide(diagonal,union,out=np.zeros(k),where=union>0)
            f1=np.divide(2*diagonal,reference_counts+prediction_counts,out=np.zeros(k),where=reference_counts+prediction_counts>0)
            reliability=[[float(s/n),float(c/n),int(n)] for n,s,c in bins if n>0]
            metrics=dict(zip(('overall_accuracy','macro_f1','mean_iou'),scores(matrix)))
            metrics.update(classes=classes.tolist(),precision=precision.tolist(),recall=recall.tolist(),f1=f1.tolist(),iou=iou.tolist(),
                support=reference_counts.tolist(),confusion_matrix_reference_rows=matrix.tolist(),cells=paired,
                reference_cells=total_reference,training_excluded_cells=excluded,unclassified_reference_cells=unclassified,
                coverage=paired/(total_reference-excluded),multiclass_brier=brier/paired,log_loss=loss/paired,
                reliability=reliability,ece=sum(abs(p-o)*n for p,o,n in reliability)/paired,
                block_m=block_m,training_buffer_m=buffer_m,occupied_blocks=len(blocks),interval95=intervals,
                replicates=replicates,seed=seed)
            require(all(digest(p)==h for p,h in hashes.items()),'Evaluation input changed during processing.');check()
            receipt={'schema':'geofathom-independent-classification-1','metrics':metrics,'sha256':digest(staged),
                'source_sha256':{config.get('source_names',{}).get(p,p):h for p,h in hashes.items()},
                'reference_description':config['reference_description'],'model_sha256':digest(model_path),
                'assumptions':'User-supplied independent reference; training locations and specified projected Chebyshev buffer excluded; exchangeable spatial blocks; percentile intervals conditional on reference quality and sampled support.'}
            os.link(staged,output);return receipt
        finally:
            if staged is not None:staged.unlink(missing_ok=True)
