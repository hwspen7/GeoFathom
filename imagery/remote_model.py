"""Spatially validated portable random forests and full-resolution disk inference.

Models contain numeric JSON trees, never pickle or executable user objects.
Optional spatially isolated temperature calibration remains conditional on sampled support.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.windows import Window

from analysis.science_raster import require
from .remote_band import read_calibrated
from .remote_kernels import quality_mask
from .remote_confidence import calibrated_probabilities,fit_temperature,probability_scores,feature_support,support_distance
from .remote_partitions import sample_partitions
from .remote_windowed import digest, same_grid, windows


class Inputs:
    def __init__(self, stack, features, quality=(), labels=None):
        require(1 <= len(features) <= 16, 'Use 1–16 explicitly named model features.')
        self.roles = list(features)
        self.bands = {}
        self.details = {}
        self.hashes = {}
        self.grid = None
        def band(spec, quantity):
            path = str(Path(spec['path']).resolve())
            ds = stack.enter_context(rasterio.open(path))
            require(ds.driver == 'GTiff' and ds.crs, 'Use georeferenced GeoTIFFs.')
            if self.grid is None: self.grid = ds
            require(same_grid(ds, self.grid), 'Prepare all model bands and labels on the same explicit grid.')
            require(ds.width*ds.height <= 150_000_000 and ds.transform.a > 0 and ds.transform.e < 0
                    and ds.transform.b == ds.transform.d == 0, 'Use bounded north-up model inputs.')
            binding = SimpleNamespace(band=spec.get('band', 1), encoding=spec.get('encoding', 'metadata'),
                scale=spec.get('scale', 1), offset=spec.get('offset', 0), unit=spec.get('unit', ''))
            require(binding.encoding in ('metadata', 'raw', 'custom', 'landsat_sr'), 'Unknown model calibration.')
            _, unit, _, _ = read_calibrated(ds, binding, quantity, Window(0,0,0,0))
            if path not in self.hashes:self.hashes[path]=digest(path)
            return ds, binding, quantity, unit
        for r, spec in features.items():
            require(spec.get('quantity', 'reflectance') in ('reflectance','numeric','power','db','slope','aspect','kelvin','distance_m','fraction'), 'Declare a supported physical model feature quantity.')
            self.bands[r] = band(spec, spec.get('quantity', 'reflectance'))
            ds,b,q,unit=self.bands[r]
            self.details[r]={'band':b.band,'quantity':q,'unit':unit,'crs':str(ds.crs),
                'transform':list(ds.transform)[:6],'shape':[ds.height,ds.width],
                'acquisition_datetime':ds.tags(b.band).get('ACQUISITION_DATETIME'),
                'source_sha256':self.hashes[str(Path(spec['path']).resolve())]}
        self.labels = band({**labels, 'encoding':'raw'}, 'class') if labels else None
        self.quality = []
        for q in quality:
            require(q['scheme'] in ('binary','sentinel_clear','landsat_clear','landsat_unsaturated'), 'Unknown model QA scheme.')
            require(set(q.get('roles', [])) <= set(features), 'Unknown model quality target role.')
            self.quality.append((q, band({**q, 'encoding':'raw'}, 'class')))

    def read(self, window):
        masks={}
        for spec,(ds,b,q,_) in self.quality:
            clear = quality_mask(read_calibrated(ds,b,q,window)[0],spec['scheme']) == 1
            for r in spec.get('roles') or self.roles:
                masks[r]=clear.copy() if r not in masks else masks[r]&clear
        values = {r: read_calibrated(ds,b,q,window,validity=masks.get(r))[0] for r,(ds,b,q,_) in self.bands.items()}
        return np.stack(list(values.values()))

    def unchanged(self):
        require(all(digest(p)==h for p,h in self.hashes.items()), 'Model input changed during processing.')


def classification_metrics(truth, prediction, classes):
    from sklearn.metrics import confusion_matrix
    cm=confusion_matrix(truth,prediction,labels=classes)
    diagonal=np.diag(cm);support=cm.sum(axis=1);predicted=cm.sum(axis=0)
    recall=np.divide(diagonal,support,out=np.zeros(len(classes)),where=support>0)
    precision=np.divide(diagonal,predicted,out=np.zeros(len(classes)),where=predicted>0)
    f1=np.divide(2*precision*recall,precision+recall,out=np.zeros(len(classes)),where=precision+recall>0)
    union=support+predicted-diagonal
    iou=np.divide(diagonal,union,out=np.zeros(len(classes)),where=union>0)
    return {'classes':[int(c) for c in classes],'confusion_matrix_reference_rows':cm.tolist(),
        'cells':int(cm.sum()),'overall_accuracy':float(diagonal.sum()/cm.sum()),
        'balanced_accuracy':float(recall[support>0].mean()),'macro_f1':float(f1.mean()),
        'mean_iou':float(iou[union>0].mean()),'precision':precision.tolist(),'recall':recall.tolist(),
        'f1':f1.tolist(),'iou':iou.tolist(),'support':support.tolist()}


def export_forest(estimator):
    trees=[]
    for item in estimator.estimators_:
        tree=item.tree_;prob=tree.value[:,0,:].copy();prob/=prob.sum(axis=1,keepdims=True)
        trees.append({'left':tree.children_left.tolist(),'right':tree.children_right.tolist(),
            'feature':tree.feature.tolist(),'threshold':tree.threshold.tolist(),'probability':prob.tolist()})
    return trees


def compile_forest(model):
    require(model.get('schema')=='geofathom-random-forest-1','Unsupported model schema.')
    classes=np.asarray(model['classes']);d=len(model['features']);trees=model['trees']
    require(2<=len(classes)<=32 and np.all(classes>0) and np.all(classes==np.floor(classes))
            and len(np.unique(classes))==len(classes),'Invalid model class identities.')
    require(1<=d<=16 and 1<=len(trees)<=128,'Model work budget exceeded.')
    compiled=[];nodes=0
    for t in trees:
        left=np.asarray(t['left'],dtype=np.int64);right=np.asarray(t['right'],dtype=np.int64)
        feature=np.asarray(t['feature'],dtype=np.int64);threshold=np.asarray(t['threshold'],float)
        prob=np.asarray(t['probability'],float);n=len(left);ids=np.arange(n);leaf=left==-1
        nodes+=n;require(n>=1 and nodes<=300_000 and left.shape==right.shape==feature.shape==threshold.shape==(n,)
                         and prob.shape==(n,len(classes)),'Invalid forest arrays or model budget.')
        require(np.all(right[leaf]==-1) and np.all((left[~leaf]>ids[~leaf])&(left[~leaf]<n))
                and np.all((right[~leaf]>ids[~leaf])&(right[~leaf]<n)),'Tree children must be forward, finite nodes.')
        require(np.all((feature[~leaf]>=0)&(feature[~leaf]<d)) and np.isfinite(threshold).all()
                and np.isfinite(prob).all() and np.all(prob>=0) and np.allclose(prob.sum(axis=1),1), 'Invalid tree feature or probability.')
        compiled.append((left,right,feature,threshold,prob))
    return compiled


def forest_probabilities(compiled, features):
    # scikit-learn's tree evaluator also compares float32 input to float64 thresholds.
    x=np.asarray(features,dtype=np.float32);out=np.zeros((len(x),compiled[0][-1].shape[1]))
    require(np.isfinite(x).all(),'Features exceed the portable float32 model domain.')
    for left,right,feature,threshold,prob in compiled:
        ids=np.zeros(len(x),dtype=np.int64)
        for _ in range(64):
            active=left[ids]!=-1
            if not active.any(): break
            q=np.flatnonzero(active);node=ids[q]
            ids[q]=np.where(x[q,feature[node]]<=threshold[node],left[node],right[node])
        require(np.all(left[ids]==-1),'Portable tree exceeds depth budget.')
        out+=prob[ids]
    return out/len(compiled)


def train(config, output, progress=None, check=lambda:None):
    from sklearn.ensemble import RandomForestClassifier
    import sklearn
    output=Path(output).resolve();require(output.parent.is_dir() and not output.exists(),'Choose a new model output.')
    tile=config.get('tile',256);require(type(tile) is int and 32<=tile<=512,'Training tile must be 32–512.')
    with ExitStack() as stack:
        inputs=Inputs(stack,config['features'],config.get('quality',[]),config['labels'])
        grid=inputs.grid
        require(grid.crs.is_projected and grid.crs.linear_units in ('metre','meter'),'Spatial training requires a projected metre grid.')
        samples=[];labels=[];rows=[];cols=[];count=0
        ds,binding,quantity,_=inputs.labels
        require(ds.tags().get('SAMPLE_SPLIT')!='reference','Reference-only sample rasters cannot train a model.')
        label_provenance={k:ds.tags()[k] for k in ('SAMPLE_REVISION_SHA256','SAMPLE_SPLIT','CLASS_CODEBOOK') if k in ds.tags()}
        for window in windows(grid.width,grid.height,tile):
            check();target=read_calibrated(ds,binding,quantity,window)[0]
            if not np.any(np.isfinite(target)&(target>0)):continue
            values=inputs.read(window)
            good=np.isfinite(values).all(axis=0)&np.isfinite(target)&(target>0)
            rr,cc=np.nonzero(good);count+=len(rr)
            require(count<=10000,'Use at most 10,000 explicitly selected labeled samples; no silent subsampling.')
            samples.append(values[:,good].T);labels.append(target[good]);rows.extend((rr+int(window.row_off)).tolist());cols.extend((cc+int(window.col_off)).tolist())
        require(count>=40,'Use at least forty complete labeled samples.')
        # Canonical sample order makes bootstrap training independent of I/O tiles.
        order=np.lexsort((cols,rows));x=np.concatenate(samples)[order];y=np.concatenate(labels).astype(int)[order]
        rows=np.asarray(rows)[order].tolist();cols=np.asarray(cols)[order].tolist();classes=np.unique(y)
        require(len(x)>=40 and 2<=len(classes)<=32,'Use at least forty samples and 2–32 classes.')
        p={'trees':64,'max_depth':12,'min_leaf':2,'seed':42,'block_m':1000.,'folds':5,'buffer_blocks':1,'calibrate':False,**config.get('parameters',{})}
        require(set(p)=={'trees','max_depth','min_leaf','seed','block_m','folds','buffer_blocks','calibrate'},'Unknown training parameter.')
        for key,lo,hi in [('trees',16,128),('max_depth',2,16),('min_leaf',1,100),('seed',0,2147483647),('folds',3,10),('buffer_blocks',0,1)]:
            require(type(p[key]) is int and lo<=p[key]<=hi,'Invalid training parameter: '+key)
        require(type(p['calibrate']) is bool,'Calibration must be explicitly enabled or disabled.')
        require(np.isfinite(p['block_m']) and 1<=p['block_m']<=100000,'Invalid spatial block size.')
        folds,excluded=sample_partitions(np.asarray(rows),np.asarray(cols),grid.transform,p['block_m'],p['folds'],p['buffer_blocks'])
        def estimator():return RandomForestClassifier(n_estimators=p['trees'],max_depth=p['max_depth'],
            min_samples_leaf=p['min_leaf'],class_weight='balanced',random_state=p['seed'],n_jobs=1)
        oof=np.full((len(x),len(classes)),np.nan);raw_oof=oof.copy();uncalibrated_oof=oof.copy();fold_rows=[]
        for j in range(p['folds']):
            check();hold=folds==j;training=~excluded[j]
            require(all(np.count_nonzero(training&(y==c))>=5 and np.count_nonzero(hold&(y==c))>=1 for c in classes),
                    'Every spatial fold needs five training and one held-out sample per class.')
            model=estimator().fit(x[training],y[training]);raw_oof[hold]=model.predict_proba(x[hold])
            calibration_fold=(j+1)%p['folds'];calibration=(folds==calibration_fold)&training
            calibration_training=training&~excluded[calibration_fold];temperature=1.
            if p['calibrate']:
                require(all(np.count_nonzero(calibration_training&(y==c))>=5 and np.count_nonzero(calibration&(y==c))>=1 for c in classes),
                    'Nested spatial calibration needs five fit and one calibration sample per class after both buffers.')
                inner=estimator().fit(x[calibration_training],y[calibration_training])
                temperature=fit_temperature(inner.predict_proba(x[calibration]),y[calibration],classes)
                # The exact same fitted estimator reaches calibration and outer holdout.
                uncalibrated_oof[hold]=inner.predict_proba(x[hold])
                oof[hold]=calibrated_probabilities(uncalibrated_oof[hold],temperature)
            else:oof[hold]=raw_oof[hold];uncalibrated_oof[hold]=raw_oof[hold]
            fold_rows.append({'fold':j,'training_cells':int(training.sum()),'validation_cells':int(hold.sum()),
                'buffer_excluded':int((~training&~hold).sum()),'calibration_cells':int(calibration.sum()) if p['calibrate'] else 0,
                'calibration_fold':calibration_fold if p['calibrate'] else None,'calibration_training_cells':int(calibration_training.sum()) if p['calibrate'] else None,'temperature':temperature,'accuracy':float(np.mean(classes[np.argmax(oof[hold],axis=1)]==y[hold]))})
            if progress:progress(.2+.6*(j+1)/p['folds'])
        require(np.isfinite(oof).all(),'Incomplete spatial out-of-fold predictions.')
        validation=classification_metrics(y,classes[np.argmax(oof,axis=1)],classes)
        validation.update(**probability_scores(oof,y,classes),raw_probability_scores=probability_scores(uncalibrated_oof,y,classes),
            folds=fold_rows,scheme='buffered_recursive_spatial_blocks',parameters=p,
            calibration_scope='Outer holdout excluded from inner calibration and its estimator; final temperature fitted from raw spatial OOF predictions.')
        temperature=fit_temperature(raw_oof,y,classes) if p['calibrate'] else 1.
        check();model=estimator().fit(x,y)
        mean=x.mean(axis=0);cov=np.atleast_2d(np.cov(x,rowvar=False));scale=max(float(np.trace(cov)/len(mean)),1e-12)
        covariance=.95*cov+.05*scale*np.eye(len(mean))
        identities={config.get('source_names',{}).get(p,p):h for p,h in inputs.hashes.items()}
        artifact={'schema':'geofathom-random-forest-1','classes':classes.tolist(),
            'features':[{'role':r,'unit':inputs.bands[r][3],'quantity':inputs.bands[r][2],'training_source':inputs.details[r]} for r in inputs.roles],
            'trees':export_forest(model),'validation':validation,'source_sha256':identities,
            'training_label_sha256':digest(config['labels']['path']),'label_provenance':label_provenance,
            'training_grid':{'crs':str(grid.crs),'transform':list(grid.transform)[:6],'shape':[grid.height,grid.width]},
            'training_samples':{'rows':rows,'cols':cols},'training_mean':mean.tolist(),'training_covariance':covariance.tolist(),
            'feature_support':feature_support(x),'probability_calibration':{'method':'spatial_oof_temperature' if p['calibrate'] else 'identity','temperature':temperature},
            'sklearn_version':sklearn.__version__,'probability_interpretation':('Spatial-OOF temperature-calibrated probabilities, conditional on training domain.' if p['calibrate'] else 'Uncalibrated forest vote probabilities.')+' Standardized training distance is descriptive, not an OOD probability.'}
        # Enforce serialization budgets and verify portable inference against the fitted estimator.
        compiled=compile_forest(artifact)
        require(np.allclose(forest_probabilities(compiled,x[:256]),model.predict_proba(x[:256]),atol=1e-12,rtol=0),'Portable model disagrees with trained estimator.')
        data=json.dumps(artifact,separators=(',',':'),allow_nan=False).encode()
        require(len(data)<=64*1024**2,'Portable model exceeds 64 MiB.')
        inputs.unchanged();check()
        fd,name=tempfile.mkstemp(prefix='.model-'+output.stem+'-',suffix='.json',dir=output.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(data)
            os.link(name,output)
        finally:Path(name).unlink(missing_ok=True)
        return {'schema':artifact['schema'],'sha256':digest(output),'features':artifact['features'],
            'classes':classes.tolist(),'validation':validation,'source_sha256':identities,'probability_calibration':artifact['probability_calibration'],
            'interpretation':'Saved numeric forest refitted on all labels; accuracy comes only from spatial OOF predictions.'}


def predict(config, output, progress=None, check=lambda:None):
    model_path=Path(config['model_path']).resolve();require(model_path.stat().st_size<=64*1024**2,'Model exceeds 64 MiB.')
    model=json.loads(model_path.read_text());compiled=compile_forest(model);model_hash=digest(model_path)
    output=Path(output).resolve();require(output.parent.is_dir() and not output.exists(),'Choose a new prediction output.')
    tile=config.get('tile',256);require(type(tile) is int and 32<=tile<=512,'Prediction tile must be 32–512.')
    minimum=config.get('minimum_probability',0.);require(np.isfinite(minimum) and 0<=minimum<=1,'Invalid abstention probability threshold.')
    maximum_distance=config.get('maximum_training_distance');require(maximum_distance is None or np.isfinite(maximum_distance) and maximum_distance>0,'Invalid training distance rejection threshold.')
    require(set(config['features'])=={f['role'] for f in model['features']},'Bind exactly the trained feature roles.')
    ordered={f['role']:config['features'][f['role']] for f in model['features']}
    classes=np.asarray(model['classes']);k=len(classes);temp=None
    with ExitStack() as stack:
        inputs=Inputs(stack,ordered,config.get('quality',[]));grid=inputs.grid
        require(all(inputs.bands[f['role']][2:]==(f['quantity'],f['unit']) for f in model['features']), 'Prediction feature quantities/units differ from training.')
        support=model.get('feature_support');sums=np.zeros(len(ordered));outside=np.zeros(len(ordered),dtype=np.int64);distance_exceeded=0
        band_names=['class','maximum_probability','entropy_bits','training_spectral_distance',*['probability_class_'+str(c) for c in classes]]
        count=accepted=0;total=((grid.width+tile-1)//tile)*((grid.height+tile-1)//tile)
        try:
            fd,name=tempfile.mkstemp(prefix='.prediction-'+output.stem+'-',suffix='.tif',dir=output.parent);os.close(fd);temp=Path(name)
            with rasterio.open(temp,'w',driver='GTiff',width=grid.width,height=grid.height,count=k+4,dtype='float64',
                crs=grid.crs,transform=grid.transform,nodata=np.nan,compress='deflate',tiled=True,blockxsize=256,blockysize=256,BIGTIFF='IF_SAFER') as dst:
                dst.update_tags(REMOTE_SCHEMA='geofathom-rf-prediction-1',MODEL_SHA256=model_hash)
                for i,title in enumerate(band_names):
                    dst.set_band_description(i+1,title);dst.update_tags(i+1,TERRAIN_UNIT='class' if i==0 else 'bit' if i==2 else 'unitless')
                for n,window in enumerate(windows(grid.width,grid.height,tile)):
                    check();values=inputs.read(window);valid=np.isfinite(values).all(axis=0)
                    result=np.full((k+4,int(window.height),int(window.width)),np.nan)
                    if valid.any():
                        x=values[:,valid].T;prob=calibrated_probabilities(forest_probabilities(compiled,x),model.get('probability_calibration',{}).get('temperature',1));maximum=prob.max(axis=1)
                        entropy=-np.sum(np.where(prob>0,prob*np.log2(np.maximum(prob,1e-300)),0),axis=1)
                        distance=support_distance(x,model)
                        if support:
                            sums+=x.sum(axis=0);outside+=((x<np.asarray(support['lower']))|(x>np.asarray(support['upper']))).sum(axis=0)
                            distance_exceeded+=int((distance>support['distance_p95']).sum())
                        label=classes[np.argmax(prob,axis=1)].astype(float);label[(maximum<minimum)|((distance>maximum_distance) if maximum_distance is not None else False)]=np.nan
                        result[:,valid]=np.vstack((label,maximum,entropy,distance,prob.T))
                        count+=len(x);accepted+=int(np.isfinite(label).sum())
                    dst.write(result,window=window)
                    if progress:progress(.95*(n+1)/total)
            require(count>0,'No complete prediction support.');inputs.unchanged();check()
            require(digest(model_path)==model_hash,'Model changed during prediction.')
            receipt={'schema':'geofathom-rf-prediction-1','model_sha256':model_hash,
                'source_sha256':{config.get('source_names',{}).get(p,p):h for p,h in inputs.hashes.items()},
                'band_layout':{name:i+1 for i,name in enumerate(band_names)},'valid_cells':count,'classified_cells':accepted,
                'abstained_cells':count-accepted,'minimum_probability':minimum,'sha256':digest(temp),
                'crs':str(grid.crs),'transform':list(grid.transform)[:6],'shape':[grid.height,grid.width],
                'probability_calibration':model.get('probability_calibration',{'method':'identity','temperature':1}),
                'maximum_training_distance':maximum_distance,'domain_diagnostics':{'outside_marginal_support_fraction':dict(zip(ordered,(outside/count).tolist())),
                    'mean_shift_training_sd':dict(zip(ordered,((sums/count-np.asarray(support['mean']))/np.asarray(support['scale'])).tolist())),
                    'beyond_training_distance_p95_fraction':distance_exceeded/count,'scope':support['scope']} if support else None,
                'interpretation':model['probability_interpretation']}
            os.link(temp,output)
            return receipt
        finally:
            if temp is not None:temp.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['train','predict'])
    parser.add_argument('config',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    result=(train if args.action=='train' else predict)(json.loads(args.config.read_text()),args.output)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
