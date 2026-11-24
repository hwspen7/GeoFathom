"""Conditional local spatial inference with explicit exchangeability and multiplicity assumptions."""
import numpy as np
from .studio_data import FigureInputError

def adjust_by(p):
    """Benjamini–Yekutieli adjustment, valid under arbitrary dependence."""
    values=np.asarray(p,float)
    if not len(values):return values.copy()
    order=np.argsort(values,kind='stable');m=len(values)
    harmonic=np.sum(1/np.arange(1,m+1,dtype=float))
    adjusted=np.minimum.accumulate((values[order]*m*harmonic/np.arange(1,m+1))[::-1])[::-1]
    out=np.empty_like(values);out[order]=np.clip(adjusted,0,1)
    return out

def conditional_moran(u,lag,count,permutations,seed):
    """Randomly sample k distinct other observations per focal cell and draw.

    The two-sided statistic is centered at the conditional null mean; the
    plus-one Monte Carlo p-value never equals zero. No Gaussian approximation.
    """
    mask=np.isfinite(u);pool=u[mask];n=len(pool)
    eligible=mask&np.isfinite(lag)&(count>0)
    if n<5 or not eligible.any():raise FigureInputError('Local inference requires at least five valid cells with neighbors.')
    if int(eligible.sum())*permutations*4>24_000_000:
        raise FigureInputError('Local permutation inference exceeds draw budget. Reduce area or permutations.')
    if permutations<99:raise FigureInputError('At least 99 permutations required.')
    pos=np.full(u.shape,-1,dtype=np.int64);pos[mask]=np.arange(n)
    p=np.full(u.shape,np.nan);rng=np.random.default_rng(seed)
    for k in range(1,5):
        flat=np.flatnonzero(eligible.ravel()&(count.ravel()==k))
        for start in range(0,len(flat),256):
            loc=flat[start:start+256];focal=pos.ravel()[loc];v=u.ravel()[loc];observed=v*lag.ravel()[loc]
            expected=-v*v/(n-1)
            target=np.abs(observed-expected)[:,None]
            shape=(len(loc),permutations);draws=[]
            # Sequential uniform sampling with rejection yields a uniform ordered
            # sample without replacement from all other valid observations.
            for j in range(k):
                idx=rng.integers(0,n-1,size=shape)
                if draws:
                    bad=np.logical_or.reduce([idx==prior for prior in draws])
                    while bad.any():
                        idx[bad]=rng.integers(0,n-1,size=int(bad.sum()))
                        bad=np.logical_or.reduce([idx==prior for prior in draws])
                draws.append(idx)
            vals=np.zeros(shape)
            for idx in draws:vals+=pool[idx+(idx>=focal[:,None])]
            simulated=v[:,None]*vals/k
            extreme=(np.abs(simulated-expected[:,None])>=target-1e-12).sum(axis=1)
            p.ravel()[loc]=(1+extreme)/(permutations+1)
    q=np.full_like(p,np.nan);q[eligible]=adjust_by(p[eligible])
    return p,q

def geotiff_product(grid,values,unit,recipe,sources):
    """Preserve native grid, NoData and full numerical precision for reuse."""
    import base64,hashlib,json
    from rasterio.io import MemoryFile
    values=np.ma.asarray(values,dtype=np.float64).filled(np.nan).copy()
    values[~np.isfinite(values)]=np.nan
    if values.shape!=grid.values.shape:raise FigureInputError('Derived product has mismatched dimensions.')
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',height=values.shape[0],width=values.shape[1],
             count=1,dtype='float64',crs=grid.crs,transform=grid.transform,
             nodata=float('nan'),compress='deflate',predictor=3) as ds:
            ds.write(values,1)
            ds.update_tags(TERRAIN_UNIT=unit,STUDIO_RECIPE=recipe,STUDIO_SOURCE_HASHES=json.dumps(sources))
        raw=memory.read()
    if len(raw)>24_000_000:raise FigureInputError('Derived GeoTIFF exceeds export size budget.')
    return {'name':recipe,'unit':unit,'data':base64.b64encode(raw).decode('ascii'),
            'sha256':hashlib.sha256(raw).hexdigest()}
