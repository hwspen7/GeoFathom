"""Wavelength-aware spectral continuum and separable endmember candidates."""
import numpy as np
from analysis.science_raster import require

def continuum_features(stack,wavelength,kind,p):
    w=np.asarray(wavelength,float);n,h,k=stack.shape
    require(len(w)==n and 6<=n<=64 and np.all(np.isfinite(w)) and np.all(w>0) and np.all(np.diff(w)>0),'Supply 6–64 strictly increasing positive wavelengths in nm.')
    valid=np.isfinite(stack).all(axis=0);require(valid.any(),'At least one complete spectrum required.')
    x=stack[:,valid].T
    require(np.all((x>=0)&(x<=1)),'Spectral feature extraction requires reflectance in [0,1].')
    require(len(x)*n<=2_000_000,'Spectral continuum work budget exceeded.')
    if kind=='spectral_endmembers':
        # Successive projection algorithm (SPA) assumes separability and
        # full-column-rank endmember spectra; selected points are candidates.
        count=p['endmembers'];require(count<=n and count<=len(x),'Too few bands or pixels for requested endmembers.')
        residual=x.copy();selected=[];norms=[];basis=[]
        initial=float(np.max(np.linalg.norm(x,axis=1)));require(initial>0,'Zero spectra cannot identify endmembers.')
        for _ in range(count):
            norm=np.linalg.norm(residual,axis=1);j=int(np.argmax(norm))
            require(norm[j]>initial*1e-7,'Spectral residual rank is insufficient for requested endmembers.')
            q=residual[j]/norm[j]
            residual-=np.outer(residual@q,q)
            selected.append(j);norms.append(float(norm[j]));basis.append(q)
        indices=np.argwhere(valid);rows=[]
        for j,i in enumerate(selected):
            for b,wl in enumerate(w):rows.append([j+1,int(indices[i,0]),int(indices[i,1]),float(wl),float(x[i,b])])
        return None,['endmember','row','column','wavelength_nm','reflectance'],rows,{
            'candidate_pixels':indices[selected].tolist(),'projection_norms':norms,
            'interpretation':'Deterministic successive projection candidates under separability; not verified pure materials.'}
    out=np.full(valid.shape,np.nan);values=np.full(len(x),np.nan)
    for j,y in enumerate(x):
        # Upper concave envelope: remove the middle point whenever slopes
        # increase. Linear interpolation on physical wavelength, not band index.
        hull=[]
        for i in range(n):
            while len(hull)>=2:
                a,b=hull[-2:]
                if (y[b]-y[a])*(w[i]-w[b])>(y[i]-y[b])*(w[b]-w[a]):break
                hull.pop()
            hull.append(i)
        continuum=np.interp(w,w[hull],y[hull])
        if np.any(continuum<=0):continue
        absorption=np.clip(1-y/continuum,0,1)
        if kind=='spectral_absorption_depth':values[j]=absorption.max()
        elif kind=='spectral_absorption_center':
            if absorption.max()>1e-10:values[j]=w[int(np.argmax(absorption))]
        else:values[j]=np.trapezoid(absorption,w)
    out[valid]=values
    return out,[],[],{'complete_spectra':int(valid.sum()),'wavelengths_nm':w.tolist(),
                'interpretation':'Upper-envelope continuum removal over supplied spectral interval; center is sampled wavelength of deepest feature, not sub-band fit.'}
