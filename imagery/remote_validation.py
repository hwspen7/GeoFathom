"""Support-preserving resolution conversion and independent-reference diagnostics."""
import numpy as np
from analysis.science_raster import require

def aggregate_nested(source,target,p,kind):
    require(source.crs==target.crs and source.is_meter and target.is_meter,'Nested aggregation requires the same projected metre CRS.')
    sa,ta=source.transform,target.transform
    rx=ta.a/sa.a;ry=ta.e/sa.e
    nx,ny=round(rx),round(ry)
    require(1<=nx<=100 and 1<=ny<=100 and abs(rx-nx)<1e-8 and abs(ry-ny)<1e-8,'Target must be an integer coarsening of source grid.')
    x=(ta.c-sa.c)/sa.a;y=(ta.f-sa.f)/sa.e
    c,r=round(x),round(y);h,w=target.values.shape
    require(abs(x-c)<1e-7 and abs(y-r)<1e-7,'Target edges must align with source cell boundaries.')
    require(r>=0 and c>=0 and r+h*ny<=source.values.shape[0] and c+w*nx<=source.values.shape[1],'Target footprint must be contained in source.')
    z=source.values[r:r+h*ny,c:c+w*nx].reshape(h,ny,w,nx)
    valid=np.isfinite(z);count=valid.sum(axis=(1,3));coverage=count/(nx*ny)
    out=coverage.astype(float) if kind=='align_area_coverage' else np.divide(np.where(valid,z,0).sum(axis=(1,3)),count,out=np.full((h,w),np.nan),where=(count>0)&(coverage>=p['minimum_coverage']))
    out[~np.isfinite(target.values)]=np.nan
    return out,{'source_cells_per_target':nx*ny,'minimum_coverage':p['minimum_coverage'],'low_coverage_cells':int(np.count_nonzero(np.isfinite(target.values)&(coverage<p['minimum_coverage']))),
        'model':'Exact nested equal-area cell mean over valid source support; not upsampling, sharpening or independent-error propagation.'}

def continuous_reference(v):
    a,b=v['prediction'],v['reference'];valid=np.isfinite(a)&np.isfinite(b);n=int(valid.sum())
    require(n>=3,'At least three paired reference observations required.')
    x=a[valid];y=b[valid];d=x-y;rmse=float(np.sqrt(np.mean(d*d)));bias=float(d.mean())
    yc=y-y.mean();xc=x-x.mean();den=float(yc@yc);norm=np.linalg.norm(xc)*np.linalg.norm(yc)
    out=np.full(a.shape,np.nan);out[valid]=d
    # Deterministic quantiles of actual residuals. Sample independence is not assumed.
    q=np.linspace(0,1,21)
    rows=[[float(p),float(r)] for p,r in zip(q,np.quantile(d,q))]
    meta={'paired_cells':n,'prediction_valid_cells':int(np.isfinite(a).sum()),'reference_valid_cells':int(np.isfinite(b).sum()),
          'mask_disagreement':int(np.count_nonzero(np.isfinite(a)!=np.isfinite(b))),
          'bias':bias,'rmse':rmse,'mae':float(np.mean(abs(d))),'median_error':float(np.median(d)),
          'nmad':float(1.4826*np.median(abs(d-np.median(d)))),'unbiased_rmse':float(np.sqrt(np.mean((d-bias)**2))),
          'r_squared':float(1-(d@d)/den) if den>0 else None,'pearson_r':float(np.clip(xc@yc/norm,-1,1)) if norm>0 else None,
          'interpretation':'Paired reference agreement, not uncertainty confidence intervals or proof of independent ground truth.'}
    return out,['quantile','residual'],rows,meta

def binary_reference(v):
    a,b=v['prediction'],v['reference'];valid=np.isfinite(a)&np.isfinite(b)
    require(all(np.all(np.isin(z[np.isfinite(z)],[0,1])) for z in (a,b)),'Binary prediction and reference require 0 or 1.')
    x=a[valid].astype(int);y=b[valid].astype(int)
    require(len(x)>=2 and len(np.unique(y))==2,'Reference must include both binary classes.')
    cm=np.bincount(2*y+x,minlength=4).reshape(2,2);tn,fp,fn,tp=map(int,cm.ravel())
    def div(a,b):return a/b if b else None
    recall=tp/(tp+fn);specificity=tn/(tn+fp)
    out=np.full(a.shape,np.nan);out[valid]=2*y+x
    return out,['outcome','cells'],[['true_negative',tn],['false_positive',fp],['false_negative',fn],['true_positive',tp]],{
        'confusion_matrix_reference_rows':cm.tolist(),'paired_cells':len(x),'precision':div(tp,tp+fp),'recall':recall,
        'specificity':specificity,'balanced_accuracy':(recall+specificity)/2,'f1':div(2*tp,2*tp+fp+fn),'iou':div(tp,tp+fp+fn),
        'omission_rate':1-recall,'commission_rate':div(fp,tp+fp),
        'interpretation':'Reference-positive class must be declared consistently (e.g. cloud=1); paired pixel agreement, not independent field accuracy.'}
