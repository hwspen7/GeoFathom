"""Numerical kernels for calibrated remote sensing. All masks are explicit."""
import numpy as np
from analysis.science_raster import require

def ratio(a,b):
    # Do not introduce infinities or silently replace undefined ratios by zero.
    return np.divide(a,b,out=np.full_like(a,np.nan,dtype=float),where=np.abs(b)>1e-12)

def nd(a,b):return ratio(a-b,a+b)

def optical(kind,v,p):
    if kind in {'ndvi','evi','evi2','savi','msavi2','osavi','arvi','simple_ratio','nirv'}:
        n,r=v['nir'],v['red']
        if kind=='ndvi':return nd(n,r)
        if kind=='evi':return 2.5*ratio(n-r,n+6*r-7.5*v['blue']+1)
        if kind=='evi2':return 2.5*ratio(n-r,n+2.4*r+1)
        if kind=='savi':return (1+p['soil_l'])*ratio(n-r,n+r+p['soil_l'])
        if kind=='msavi2':
            rad=(2*n+1)**2-8*(n-r)
            return (2*n+1-np.sqrt(np.where(rad>=0,rad,np.nan)))/2
        if kind=='osavi':return 1.16*ratio(n-r,n+r+.16)
        if kind=='arvi':return nd(n,2*r-v['blue'])
        if kind=='simple_ratio':return ratio(n,r)
        return n*nd(n,r)
    if kind=='ci_green':return ratio(v['nir'],v['green'])-1
    if kind=='bsi':return nd(v['swir1']+v['red'],v['nir']+v['blue'])
    a,b={'gndvi':('nir','green'),'ndre':('nir','rededge'),'ndwi':('green','nir'),
         'mndwi':('green','swir1'),'ndmi':('nir','swir1'),'nbr':('nir','swir2'),
         'nbr2':('swir1','swir2'),'ndbi':('swir1','nir'),'ndsi':('green','swir1')}[kind]
    return nd(v[a],v[b])

def quality_mask(z,scheme):
    valid=np.isfinite(z);v=z[valid]
    require(np.all(v==np.floor(v)) and np.all((v>=0)&(v<=65535)),'QA values must be raw unsigned 16-bit integers.')
    out=np.full(z.shape,np.nan);codes=v.astype(np.uint16)
    if scheme=='sentinel_clear':
        require(np.all(codes<=11),'Sentinel SCL codes must be 0–11.')
        out[valid]=np.isin(codes,[4,5,6]);out[z==0]=np.nan
    elif scheme=='landsat_clear':
        out[valid]=(codes&63)==0
        out[valid & (np.nan_to_num(z,nan=0).astype(np.uint16)&1!=0)]=np.nan
    elif scheme=='landsat_unsaturated':out[valid]=codes==0
    else:
        require(np.all(codes<=1),'Binary quality mask must contain 0 or 1.')
        out[valid]=codes
    return out

def transition(a,b,area):
    x=np.column_stack((a,b));pairs,count=np.unique(x,axis=0,return_counts=True)
    require(len(pairs)<=4096,'Transition matrix exceeds class-pair budget.')
    rows=[[int(u),int(v),int(n),float(n*area),float(n/len(a))] for (u,v),n in zip(pairs,count)]
    return ['before_class','after_class','cells','area_m2','fraction'],rows,{'paired_cells':len(a),'changed_fraction':float(np.mean(a!=b)),'valid_area_m2':float(len(a)*area)}

def agreement(a,b):
    labels=np.union1d(a,b);k=len(labels)
    require(2<=k<=64,'Agreement requires 2–64 distinct classes.')
    pred=np.searchsorted(labels,a);ref=np.searchsorted(labels,b)
    matrix=np.bincount(ref*k+pred,minlength=k*k).reshape(k,k)
    n=len(a);diag=np.diag(matrix);r=matrix.sum(axis=1);c=matrix.sum(axis=0)
    observed=float(diag.sum()/n);expected=float((r/n)@(c/n))
    rows=[[int(label),int(r[i]),int(c[i]),int(diag[i]),float(diag[i]/c[i]) if c[i] else None,
           float(diag[i]/r[i]) if r[i] else None] for i,label in enumerate(labels)]
    meta={'classes':labels.astype(int).tolist(),'confusion_matrix_reference_rows':matrix.tolist(),
          'paired_cells':n,'overall_accuracy':observed,'kappa':(observed-expected)/(1-expected) if expected<1 else None,
          'warning':'Unweighted agreement conditional on supplied reference labels; sampling design and reference independence are not verified.'}
    return ['class','reference_count','prediction_count','correct','precision','recall'],rows,meta

def temporal(kind,stack,p):
    valid=np.isfinite(stack);count=valid.sum(axis=0)
    if kind=='temporal_count':return count.astype(float),{'minimum_observations':0}
    total=np.nansum(stack,axis=0)
    mean=np.divide(total,count,out=np.full(count.shape,np.nan),where=count>=2)
    if kind=='temporal_mean':return mean,{'minimum_observations':2}
    if kind=='temporal_median':
        # Avoid all-NaN slice warnings without modifying any valid observation.
        out=np.full(count.shape,np.nan);good=count>=2
        out[good]=np.nanmedian(stack[:,good],axis=0)
        return out,{'minimum_observations':2}
    t=np.array([p['time'+str(i)] for i in range(1,5)],float)
    require(np.all(np.diff(t)>0),'Acquisition times must be strictly increasing.')
    t=t-t[0];t=t[:,None,None]
    tm=np.divide(np.sum(valid*t,axis=0),count,out=np.zeros(count.shape),where=count>0)
    dx=t-tm;dy=np.where(valid,stack-np.nan_to_num(mean,nan=0),0)
    den=np.sum(np.where(valid,dx**2,0),axis=0)
    slope=np.divide(np.sum(dx*dy,axis=0),den,out=np.full(count.shape,np.nan),where=(count>=3)&(den>0))
    return slope,{'minimum_observations':3,'acquisition_times':[p['time'+str(i)] for i in range(1,5)]}

def pca(stack,common,component):
    x=stack[:,common].T;require(len(x)>=5,'PCA requires at least five complete pixels.')
    centered=x-x.mean(axis=0);cov=centered.T@centered/(len(x)-1)
    eigen,vec=np.linalg.eigh(cov);order=np.argsort(eigen)[::-1];eigen=np.maximum(eigen[order],0);vec=vec[:,order]
    require(eigen.sum()>0,'PCA undefined for a constant spectral population.')
    for j in range(vec.shape[1]):
        i=np.argmax(abs(vec[:,j]))
        if vec[i,j]<0:vec[:,j]*=-1
    out=np.full(common.shape,np.nan);out[common]=centered@vec[:,component-1]
    rows=[[i+1,float(v),float(v/eigen.sum()),*vec[:,i].tolist()] for i,v in enumerate(eigen)]
    return out,['component','eigenvalue','explained_fraction','blue','green','red','nir'],rows,{'component':component,'complete_pixels':len(x),'degenerate_eigenspaces':bool(np.any(np.diff(eigen)==0))}

def classify(stack,labels):
    valid=np.isfinite(stack).all(axis=0);train=valid&np.isfinite(labels)&(labels>0)
    classes=np.unique(labels[train]);require(2<=len(classes)<=32,'Provide 2–32 positive training classes.')
    require(np.count_nonzero(valid)*len(classes)*stack.shape[0]<=80_000_000,'Classification exceeds work budget.')
    centers=[];rows=[]
    for c in classes:
        data=stack[:,train&(labels==c)].T;require(len(data)>=2,'Each class requires at least two complete training pixels.')
        center=data.mean(axis=0);centers.append(center);rows.append([int(c),len(data),*center.tolist()])
    centers=np.asarray(centers);require(len(np.unique(centers,axis=0))==len(classes),'Training class centroids are indistinguishable.')
    x=stack[:,valid].T;pred=np.empty(len(x))
    for i in range(0,len(x),8192):
        delta=x[i:i+8192,None,:]-centers[None,:,:]
        pred[i:i+len(delta)]=classes[np.argmin(np.sum(delta**2,axis=2),axis=1)]
    out=np.full(valid.shape,np.nan);out[valid]=pred
    return out,['class','training_cells','blue','green','red','nir'],rows,{'classes':classes.astype(int).tolist(),'training_cells':int(train.sum()),'classified_cells':len(x),'tie_break':'lowest class code'}
