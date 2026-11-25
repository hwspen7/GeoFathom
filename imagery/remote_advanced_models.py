"""Analysis-ready polarimetry, kernel BRDF, spatial fusion and cloud inference."""
import numpy as np
from analysis.science_raster import require
from .remote_partitions import spatial_partitions

def dualpol(v,kind):
    a,b,r,i=(v[k] for k in ('c11','c22','c12_real','c12_imag'))
    valid=np.logical_and.reduce([np.isfinite(q) for q in v.values()])
    require(valid.any(),'No complete covariance observations.')
    # Normalize before eigenanalysis to avoid scale-dependent PSD tolerance.
    total=a[valid]+b[valid];good=total>0
    x=a[valid][good]/total[good];y=b[valid][good]/total[good]
    c=(r[valid][good]+1j*i[valid][good])/total[good]
    require(np.all(abs(c)**2<=x*y+1e-10),'Dual-pol covariance matrix must be positive semidefinite.')
    require(np.all((r[valid][~good]==0)&(i[valid][~good]==0)),'Zero-power covariance cannot have nonzero cross terms.')
    contrast=np.clip(np.hypot(x-y,2*abs(c)),0,1)
    prob=np.column_stack(((1+contrast)/2,(1-contrast)/2))
    if kind=='sar_dual_entropy':
        logs=np.zeros_like(prob);np.log2(prob,out=logs,where=prob>0);value=-np.sum(prob*logs,axis=1)
    elif kind=='sar_dual_purity':value=contrast
    else:value=prob[:,1]
    out=np.full(a.shape,np.nan);z=np.full(len(total),np.nan);z[good]=value;out[valid]=z
    return out,{'zero_power_cells':int((~good).sum()),'model':'Two-channel Hermitian covariance eigenvalues; normalized dual-pol entropy, purity or minor eigenvalue fraction. Not full quad-pol H/A/alpha decomposition.'}

def ross_li(solar,view,azimuth):
    s,v,a=np.deg2rad([solar,view,azimuth]);cs,cv=np.cos(s),np.cos(v)
    cosxi=np.clip(cs*cv+np.sin(s)*np.sin(v)*np.cos(a),-1,1);xi=np.arccos(cosxi)
    vol=((np.pi/2-xi)*cosxi+np.sin(xi))/(cs+cv)-np.pi/4
    ts,tv=np.tan(s),np.tan(v);secs,secv=1/cs,1/cv
    d2=max(0,ts*ts+tv*tv-2*ts*tv*np.cos(a))
    cost=np.clip(2*np.sqrt(d2+(ts*tv*np.sin(a))**2)/(secs+secv),-1,1);t=np.arccos(cost)
    overlap=(t-np.sin(t)*np.cos(t))*(secs+secv)/np.pi
    geo=overlap-secs-secv+.5*(1+cosxi)*secs*secv
    return float(vol),float(geo)

def brdf(v,p):
    # RossThick–LiSparse reciprocal, h/b=2 and b/r=1.
    a,b=ross_li(p['solar_zenith'],p['view_zenith'],p['relative_azimuth'])
    c,d=ross_li(p['target_solar_zenith'],p['target_view_zenith'],p['target_relative_azimuth'])
    iso,vol,geo=(v[k] for k in ('f_iso','f_vol','f_geo'))
    require(all(np.all(z[np.isfinite(z)]>=0) for z in (iso,vol,geo)),'Use nonnegative externally fitted BRDF coefficients.')
    src=iso+a*vol+b*geo;target=iso+c*vol+d*geo
    good=np.isfinite(v['reflectance'])&np.isfinite(src)&np.isfinite(target)&(src>p['min_model'])&(target>0)
    out=np.full(src.shape,np.nan);out[good]=v['reflectance'][good]*target[good]/src[good]
    bad=np.isfinite(out)&((out<-.2)|(out>1.6));out[bad]=np.nan
    return out,{'source_kernels':[a,b],'target_kernels':[c,d],'outside_supported_cells':int(bad.sum()),
                'interpretation':'RossThick–LiSparse reciprocal c-factor correction using supplied band coefficients; constant geometry, no coefficient retrieval.'}

def support_fusion(v,p):
    # One-pair local change transfer followed by exact coarse support constraint.
    # Coarse inputs must be replicated over exact aligned native coarse blocks.
    f,c0,c1=(v[k] for k in ('fine_before','coarse_before','coarse_after'));h,w=f.shape;k=p['block_cells'];r=p['radius']
    require(h%k==0 and w%k==0 and f.size*(2*r+1)**2<=40_000_000,'Fusion needs complete nested blocks within work budget.')
    def blocks(z):return z.reshape(h//k,k,w//k,k).transpose(0,2,1,3)
    for z in (c0,c1):
        q=blocks(z);valid=np.isfinite(q);count=valid.sum(axis=(2,3))
        require(np.all((count==0)|(count==k*k)),'Coarse support blocks must be entirely valid or entirely missing.')
        diff=np.max(np.where(valid,q,-np.inf),axis=(2,3))-np.min(np.where(valid,q,np.inf),axis=(2,3))
        require(np.all(diff[count>0]<=1e-9),'Coarse inputs must be native block values replicated without interpolation.')
    valid=np.isfinite(f)&np.isfinite(c0)&np.isfinite(c1);delta=c1-c0
    pad=lambda z:np.pad(z,r,constant_values=np.nan)
    fp,dp=pad(f),pad(delta);numer=np.zeros(f.shape);mass=np.zeros(f.shape)
    for dy in range(-r,r+1):
        for dx in range(-r,r+1):
            fn=fp[r+dy:r+dy+h,r+dx:r+dx+w];dn=dp[r+dy:r+dy+h,r+dx:r+dx+w]
            ok=valid&np.isfinite(fn)&np.isfinite(dn)
            weight=np.zeros(f.shape)
            weight[ok]=np.exp(-.5*((fn[ok]-f[ok])/p['spectral_sd'])**2-.5*(dx*dx+dy*dy)/p['spatial_sd']**2)
            numer+=weight*np.where(ok,dn,0);mass+=weight
    candidate=f+np.divide(numer,mass,out=np.full(f.shape,np.nan),where=mass>0)
    q=blocks(candidate).copy();target=blocks(c1)[:,:,0,0];full=np.isfinite(q).all(axis=(2,3))&np.isfinite(target)
    require(full.any(),'No complete fine/coarse support blocks.')
    shift=np.zeros(target.shape);shift[full]=target[full]-q[full].mean(axis=(1,2))
    q+=shift[:,:,None,None];q[~full]=np.nan
    require(np.all((q[np.isfinite(q)]>=-.2)&(q[np.isfinite(q)]<=1.6)),'Support constraint yields out-of-range reflectance; review input harmonization.')
    out=q.transpose(0,2,1,3).reshape(h,w)
    return out,{'valid_coarse_blocks':int(full.sum()),'maximum_coarse_mean_error':float(np.max(abs(q[full].mean(axis=(1,2))-target[full]))),
                'interpretation':'Spectral/spatial Gaussian-weighted temporal difference transfer followed by coarse-block mean constraint. Not the published STARFM/ESTARFM algorithm; assumes harmonized sensors, aligned equal-area nested supports and complete fine blocks.'}

def cloud_model(v,grid,p,kind):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import log_loss,confusion_matrix
    from threadpoolctl import threadpool_limits
    import sklearn
    bands=('blue','green','red','nir','swir1','swir2')
    stack=np.stack([v[k] for k in bands]);label=v['training']
    valid=np.isfinite(stack).all(axis=0);labeled=valid&np.isfinite(label)&(label>0)
    require(grid.is_meter,'Cloud spatial validation requires a projected metre grid.')
    require(60<=labeled.sum()<=20000 and valid.sum()<=500000,'Cloud model requires 60–20,000 labels and bounded complete pixels.')
    classes=np.unique(label[labeled]);require(np.array_equal(classes,[1,2,3]),'Training labels must include 1=clear, 2=cloud and 3=shadow; zero=unlabeled.')
    fold,excluded=spatial_partitions(valid.shape,grid.transform,p['block_m'],p['folds'],p['buffer_blocks'])
    mat=np.zeros((3,3),int);brier=0.;loss=0.;count=0;rows=[]
    def estimator():return HistGradientBoostingClassifier(max_iter=p['iterations'],max_leaf_nodes=p['leaves'],min_samples_leaf=5,l2_regularization=1,early_stopping=False,random_state=42)
    with threadpool_limits(limits=1):
        for j in range(p['folds']):
            hold=labeled&(fold==j);train=labeled&~excluded[j]
            require(all(np.count_nonzero(train&(label==c))>=10 and np.count_nonzero(hold&(label==c))>=2 for c in classes),'Each cloud fold needs ten training and two validation observations per class.')
            model=estimator();model.fit(stack[:,train].T,label[train]);prob=model.predict_proba(stack[:,hold].T)
            truth=label[hold].astype(int);one=np.eye(3)[truth-1];n=len(truth);pred=classes[np.argmax(prob,axis=1)]
            cm=confusion_matrix(truth,pred,labels=classes);mat+=cm
            bs=float(np.sum((prob-one)**2));ll=float(log_loss(truth,prob,labels=classes))
            brier+=bs;loss+=ll*n;count+=n;rows.append([j,int(train.sum()),n,bs/n,ll,float(np.trace(cm)/n)])
        require(count==labeled.sum(),'Cloud OOF coverage mismatch.')
        model=estimator();model.fit(stack[:,labeled].T,label[labeled])
        out=np.full(valid.shape,np.nan);x=stack[:,valid].T;z=np.empty(len(x))
        for i in range(0,len(x),8192):
            prob=model.predict_proba(x[i:i+8192]);z[i:i+len(prob)]=prob[:,1 if kind=='cloud_probability_model' else 2]
        out[valid]=z
    return out,['fold','training_cells','validation_cells','brier','log_loss','accuracy'],rows,{
        'partition':'recursive_spatial_blocks','buffer_blocks':p['buffer_blocks'],'oof_cells':count,'oof_multiclass_brier':brier/count,'oof_log_loss':loss/count,'oof_confusion_matrix':mat.tolist(),
        'oof_accuracy':float(np.trace(mat)/count),'sklearn_version':sklearn.__version__,
        'interpretation':'User-trained supervised multiclass gradient boosting with spatial OOF probability diagnostics. Training sample priors and representativeness determine probabilities; not Fmask, s2cloudless or externally calibrated cloud probability.'}
