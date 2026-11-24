"""Joint physical retrieval, independent probability calibration and two-anchor fusion."""
import numpy as np
from scipy.special import logsumexp
from analysis.science_raster import require
from .remote_advanced_models import support_fusion

def joint_retrieval(v,library,p,kind):
    t=np.asarray(library,float)
    require(t.ndim==2 and t.shape[1]==7 and 4<=len(t)<=2048 and np.isfinite(t).all(),'Joint library needs LAI,Cab,prior,blue,green,red,NIR.')
    lai,cab,prior=t[:,:3].T;spec=t[:,3:]
    require(np.all((lai>=0)&(lai<=20)&(cab>=0)&(cab<=100)&(prior>0)) and np.all((spec>=0)&(spec<=1)),'Invalid physical library values.')
    require(len(np.unique(lai))>=2 and len(np.unique(cab))>=2,'Both LAI and Cab need distinct hypotheses.')
    bands=('blue','green','red','nir');a=np.stack([v[k] for k in bands]);valid=np.isfinite(a).all(axis=0);x=a[:,valid].T
    require(0<len(x) and len(x)*len(t)<=12_000_000,'Joint retrieval work budget exceeded.')
    sd=np.array([p[k+'_sd'] for k in bands]);rho=p['band_correlation']
    corr=np.full((4,4),rho);np.fill_diagonal(corr,1)
    chol=np.linalg.cholesky(corr*sd[:,None]*sd[None,:])
    ss=np.linalg.solve(chol,spec.T).T;lp=np.log(prior);lp-=logsumexp(lp)
    out=np.full(valid.shape,np.nan);values=np.full(len(x),np.nan);mass=np.zeros(len(t));kept=0
    for i in range(0,len(x),256):
        z=np.linalg.solve(chol,x[i:i+256].T).T
        chi=np.sum((z[:,None,:]-ss[None,:,:])**2,axis=2)
        score=lp-chi/2;weight=np.exp(score-logsumexp(score,axis=1,keepdims=True))
        ml=weight@lai;mc=weight@cab;dl=lai-ml[:,None];dc=cab-mc[:,None]
        vl=np.sum(weight*dl**2,axis=1);vc=np.sum(weight*dc**2,axis=1)
        if kind=='joint_lai':q=ml
        elif kind=='joint_cab':q=mc
        elif kind=='joint_lai_sd':q=np.sqrt(vl)
        elif kind=='joint_cab_sd':q=np.sqrt(vc)
        elif kind=='joint_parameter_correlation':
            den=np.sqrt(vl*vc);q=np.divide(np.sum(weight*dl*dc,axis=1),den,out=np.full(len(z),np.nan),where=den>1e-12);q=np.clip(q,-1,1)
        else:q=1/np.sum(weight**2,axis=1)
        good=chi.min(axis=1)<=p['max_chi2'];q[~good]=np.nan
        values[i:i+len(z)]=q;mass+=weight[good].sum(axis=0);kept+=int(good.sum())
    out[valid]=values
    require(kept>0,'No pixels meet the spectral library fit threshold.')
    mass/=kept;rows=[]
    for name,axis in [('LAI',lai),('Cab',cab)]:
        for q in np.unique(axis):
            rows.append([name,float(q),float(mass[axis==q].sum())])
    return out,['parameter','value','posterior_mass'],rows,{'accepted_pixels':kept,'rejected_pixels':len(x)-kept,
        'band_correlation':rho,'library_rows':len(t),'joint_posterior':[[float(l),float(c),float(m)] for l,c,m in zip(lai,cab,mass)],
        'interpretation':'Scene-average marginal and joint posterior masses over accepted pixels; not a posterior for a single pixel or independent field accuracy. Effective hypotheses and posterior correlation diagnose ambiguity, not unique identifiability.'}

def two_anchor(v,p,kind):
    t=p['target_fraction'];require(0<t<1,'Target must lie strictly between reference acquisitions.')
    before,ma=support_fusion({'fine_before':v['fine_before'],'coarse_before':v['coarse_before'],'coarse_after':v['coarse_target']},p)
    after,mb=support_fusion({'fine_before':v['fine_after'],'coarse_before':v['coarse_after'],'coarse_after':v['coarse_target']},p)
    good=np.isfinite(before)&np.isfinite(after);require(good.any(),'No common complete reference support.')
    # Temporal barycentric weights are constant within each coarse block,
    # hence the blend preserves both anchors' target coarse mean exactly.
    blend=(1-t)*before+t*after;difference=after-before
    out=np.where(good,blend if kind=='fusion_two_anchor' else abs(difference),np.nan)
    k=p['block_cells'];h,w=out.shape
    def coarse(z):return z.reshape(h//k,k,w//k,k).mean(axis=(1,3))
    target=v['coarse_target'][::k,::k];means=coarse(blend);ok=np.isfinite(means)
    errors=means[ok]-target[ok]
    q=np.linspace(0,1,21);rows=[[float(a),float(b)] for a,b in zip(q,np.quantile(difference[good],q))]
    return out,['quantile','anchor_difference'],rows,{'reference_weights':[1-t,t],'paired_pixels':int(good.sum()),
        'anchor_disagreement_rmse':float(np.sqrt(np.mean(difference[good]**2))),
        'maximum_coarse_mean_error':float(np.max(abs(errors))),
        'interpretation':'Two bracketing support-constrained local temporal transfers, linearly blended in time. Anchor disagreement is a sensitivity diagnostic, not prediction SD. Not STARFM or ESTARFM.'}

def calibrated_cloud(v,grid,p,kind):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from scipy.optimize import minimize_scalar
    from sklearn.metrics import confusion_matrix,roc_curve,auc
    from threadpoolctl import threadpool_limits
    a=np.stack([v[k] for k in ('blue','green','red','nir','swir1','swir2')]);labels=v['training']
    valid=np.isfinite(a).all(axis=0);labeled=valid&np.isfinite(labels)&(labels>0)
    require(grid.is_meter and 90<=labeled.sum()<=12000 and valid.sum()<=300000,'Use projected metre grid, 90–12,000 labels and bounded scene.')
    require(np.array_equal(np.unique(labels[labeled]),[1,2,3]),'Require labels 1 clear, 2 cloud, 3 shadow.')
    row,col=np.indices(valid.shape);bx=np.floor((col+.5)*grid.transform.a/p['block_m']).astype(int);by=np.floor((row+.5)*abs(grid.transform.e)/p['block_m']).astype(int)
    folds=p['folds'];fold=(bx+2*by)%folds
    require(folds>=4,'Calibration requires at least four spatial folds.')
    def excluded(j):
        bad=fold==j
        if p['buffer_blocks']:
            for dx in (-1,0,1):
                for dy in (-1,0,1):bad|=(bx+dx+2*(by+dy))%folds==j
        return bad
    def fit(train):
        require(all(np.count_nonzero(train&(labels==c))>=10 for c in (1,2,3)),'Insufficient model training support per class.')
        return HistGradientBoostingClassifier(max_iter=p['iterations'],max_leaf_nodes=p['leaves'],min_samples_leaf=5,l2_regularization=1,early_stopping=False,random_state=42).fit(a[:,train].T,labels[train])
    def scaled(raw,temp):
        z=np.log(np.clip(raw,1e-15,1))/temp
        return np.exp(z-logsumexp(z,axis=1,keepdims=True))
    def loss(prob,y):return float(-np.log(np.clip(prob[np.arange(len(y)),y],1e-15,1)).mean())
    def temperature(raw,y):
        require(all(np.count_nonzero(y==c)>=2 for c in range(3)),'Insufficient calibration support per class.')
        opt=minimize_scalar(lambda t:loss(scaled(raw,t),y),bounds=(.25,4),method='bounded')
        require(opt.success,'Temperature optimization failed.')
        return float(opt.x) if opt.fun<loss(raw,y) else 1.
    raw_oof=np.full((*valid.shape,3),np.nan);oof=np.full_like(raw_oof,np.nan);rows=[]
    with threadpool_limits(limits=1):
        for j in range(folds):
            k=(j+1)%folds;hold=labeled&(fold==j);pool=labeled&~excluded(j);cal=pool&(fold==k);train=pool&~excluded(k)
            require(hold.any() and not np.any(train&cal) and not np.any((train|cal)&hold),'Spatial calibration partition is empty or overlapping.')
            model=fit(train);y=labels[hold].astype(int)-1;cy=labels[cal].astype(int)-1
            require(len(cy)>0,'No independent calibration cells.')
            temp=temperature(model.predict_proba(a[:,cal].T),cy)
            raw=model.predict_proba(a[:,hold].T);prob=scaled(raw,temp)
            raw_oof[hold]=raw;oof[hold]=prob
            rows.append([j,int(train.sum()),int(cal.sum()),int(hold.sum()),temp,loss(raw,y),loss(prob,y)])
        y=labels[labeled].astype(int)-1;raw=raw_oof[labeled];prob=oof[labeled]
        require(np.isfinite(prob).all(),'Incomplete outer validation.')
        final_temp=temperature(raw,y);model=fit(labeled);x=a[:,valid].T;out=np.full(valid.shape,np.nan);pred=[]
        target=1 if kind=='cloud_calibrated_probability' else 2
        for i in range(0,len(x),8192):pred.append(scaled(model.predict_proba(x[i:i+8192]),final_temp)[:,target])
        out[valid]=np.concatenate(pred)
    truth=(y==target).astype(int);score=prob[:,target];bins=np.minimum((score*10).astype(int),9);rel=[]
    for b in range(10):
        m=bins==b
        if m.any():rel.append([float(score[m].mean()),float(truth[m].mean()),int(m.sum())])
    fpr,tpr,_=roc_curve(truth,score,drop_intermediate=True)
    # Bound exported points, preserving endpoints.
    if len(fpr)>1024:
        ids=np.unique(np.linspace(0,len(fpr)-1,1024).astype(int));rf,rt=fpr[ids],tpr[ids]
    else:rf,rt=fpr,tpr
    return out,['fold','training_cells','calibration_cells','validation_cells','temperature','raw_log_loss','calibrated_log_loss'],rows,{
        'oof_cells':len(y),'final_temperature':final_temp,'oof_raw_log_loss':loss(raw,y),'oof_calibrated_log_loss':loss(prob,y),
        'oof_confusion_matrix':confusion_matrix(y,np.argmax(prob,axis=1),labels=[0,1,2]).tolist(),
        'reliability':rel,'ece':float(sum(abs(a-b)*n for a,b,n in rel)/len(y)),
        'binary_brier':float(np.mean((score-truth)**2)),'roc_auc':float(auc(fpr,tpr)),'roc':np.column_stack((rf,rt)).tolist(),
        'interpretation':'Independent outer spatial test folds; temperature fitted on separate inner spatial calibration folds. Final refit temperature learned from raw OOF predictions. No guarantee of external-site calibration or operational pretrained cloud detection.'}
