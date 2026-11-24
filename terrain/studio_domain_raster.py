"""Raster domain computations used by the scientific studio."""
import numpy as np
from .studio_data import FigureInputError, aligned_grids
from .studio_publication import numeric_rows

def require(ok,message):
    if not ok:raise FigureInputError(message)

def neighbors(z,diagonal=False):
    h,w=z.shape
    offsets=[(-1,0),(1,0),(0,-1),(0,1)]
    if diagonal:offsets += [(-1,-1),(-1,1),(1,-1),(1,1)]
    for dy,dx in offsets:
        result=np.full(z.shape,np.nan)
        y0,y1=max(0,-dy),min(h,h-dy);x0,x1=max(0,-dx),min(w,w-dx)
        result[y0:y1,x0:x1]=z[y0+dy:y1+dy,x0+dx:x1+dx]
        yield result

def local_moments(z,diagonal=False):
    count=np.zeros(z.shape,dtype=np.int16);s=np.zeros(z.shape);ss=np.zeros(z.shape)
    lo=np.full(z.shape,np.inf);hi=np.full(z.shape,-np.inf);sqdiff=np.zeros(z.shape)
    for v in neighbors(z,diagonal):
        valid=np.isfinite(v)
        count+=valid;s+=np.where(valid,v,0);ss+=np.where(valid,v*v,0)
        lo=np.minimum(lo,np.where(valid,v,np.inf));hi=np.maximum(hi,np.where(valid,v,-np.inf))
        sqdiff+=np.where(valid&(np.isfinite(z)),(v-z)**2,0)
    valid=(count>0)&np.isfinite(z)
    mean=np.divide(s,count,out=np.full(z.shape,np.nan),where=valid)
    var=np.maximum(0,np.divide(ss,count,out=np.full(z.shape,np.nan),where=valid)-mean**2)
    span=np.where(valid,hi-lo,np.nan)
    rms=np.sqrt(np.divide(sqdiff,count,out=np.full(z.shape,np.nan),where=valid))
    return mean,np.sqrt(var),span,rms,count

def patch_labels(z):
    """Bounded four-connected patches of equal finite class code."""
    require(z.size<=400_000,'Patch labeling currently supports up to 400,000 grid cells.')
    labels=np.zeros(z.shape,dtype=np.int32);sizes=[];codes=[];h,w=z.shape
    for i,j in np.ndindex(z.shape):
        if labels[i,j] or not np.isfinite(z[i,j]):continue
        code=z[i,j];tag=len(sizes)+1;todo=[(i,j)];labels[i,j]=tag;n=0
        while todo:
            y,x=todo.pop();n+=1
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                a,b=y+dy,x+dx
                if 0<=a<h and 0<=b<w and labels[a,b]==0 and z[a,b]==code:
                    labels[a,b]=tag;todo.append((a,b))
        sizes.append(n);codes.append(code)
    return labels,np.asarray(sizes),np.asarray(codes)

def aligned_bands(grids):
    g=grids[0]
    require(all(v.values.shape==g.values.shape and v.transform==g.transform and v.crs==g.crs for v in grids),'Spectral grids and CRS must match exactly.')
    require(all(v.unit==g.unit for v in grids),'Spectral bands must use common reflectance units.')
    a=np.stack([v.values for v in grids]);mask=np.isfinite(a).all(axis=0)
    require(mask.any(),'No common valid spectral pixels.')
    return a,mask

def safe_ratio(a,b):
    return np.divide(a,b,out=np.full_like(a,np.nan,dtype=float),where=np.abs(b)>1e-15)

def render_raster_domain(kind,req,fig,ax,grids,parameter,meta,cmap,grid_sink=None):
    g=grids[0];z=g.values;unit=g.unit or 'unspecified';derived=[]
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.ticker import MaxNLocator
    def save(headers,*arr):
        derived.clear();derived.extend(numeric_rows(headers,*arr))
    def show(out,label,cm=None,vmin=None,vmax=None,output_unit=None):
        valid=np.isfinite(out);require(valid.any(),'No valid computed raster cells.')
        im=ax.imshow(out,extent=g.extent,origin='upper',interpolation='nearest',cmap=cm or cmap,vmin=vmin,vmax=vmax)
        fig.colorbar(im,ax=ax,label=label,shrink=.82)
        geo_axes()
        v=out[valid];meta.update(used_count=int(v.size),minimum=float(v.min()),maximum=float(v.max()),mean=float(v.mean()),output_unit=label)
        if grid_sink is not None:
            from .studio_inference import geotiff_product
            grid_sink.append(geotiff_product(g,out,output_unit if output_unit is not None else label,kind,[item.sha256 for item in grids]))
        save(['valid_cells','minimum','maximum','mean'],[len(v)],[v.min()],[v.max()],[v.mean()])
    def geo_axes():
        ax.set_aspect('equal');ax.set_xlabel('Easting' if g.crs.is_projected else 'Longitude');ax.set_ylabel('Northing' if g.crs.is_projected else 'Latitude')
        ax.ticklabel_format(style='plain',useOffset=False);ax.xaxis.set_major_locator(MaxNLocator(4));ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.annotate('Grid N',xy=(.94,.92),xytext=(.94,.8),xycoords='axes fraction',textcoords='axes fraction',ha='center',fontsize=7,arrowprops={'arrowstyle':'-|>'})
        if g.is_meter:
            xmin,xmax,ymin,ymax=g.extent;length=10**np.floor(np.log10((xmax-xmin)*.2));x0=xmin+(xmax-xmin)*.06;y0=ymin+(ymax-ymin)*.06
            ax.plot([x0,x0+length],[y0,y0],color='black',linewidth=3);ax.plot([x0,x0+length],[y0,y0],color='white',linewidth=1)
            ax.text(x0+length/2,y0+(ymax-ymin)*.03,f'{length:g} m',ha='center',fontsize=7,bbox={'facecolor':'white','alpha':.8,'edgecolor':'none'})
    if kind.startswith('spectral_'):
        stack,mask=aligned_bands(grids);a=stack[:,mask]
        require(np.all((a>=0)&(a<=1)),'Spectral recipes require physical reflectance in [0,1], not raw digital numbers.')
        n=len(grids)
        if kind in {'spectral_rgb','spectral_evi'}:require(n==3,'Select exactly three bands in documented order.')
        elif kind not in {'spectral_angle','spectral_pca_variance','spectral_pca_score'}:require(n==2,'Select exactly two bands in documented order.')
        if kind=='spectral_rgb':
            rgb=np.zeros((*z.shape,4));rgb[mask,:3]=a.T;rgb[:,:,3]=mask
            ax.imshow(rgb,extent=g.extent,origin='upper',interpolation='nearest');geo_axes();meta['used_count']=int(mask.sum())
        elif kind in {'spectral_pca_variance','spectral_pca_score'}:
            require(a.shape[1]>1,'PCA needs multiple valid pixels.')
            centered=a-a.mean(axis=1,keepdims=True);cov=centered@centered.T/(a.shape[1]-1)
            eig,vec=np.linalg.eigh(cov);eig=np.maximum(eig[::-1],0);vec=vec[:,::-1];require(eig.sum()>0,'Constant spectral bands have no variance.')
            if kind=='spectral_pca_variance':
                fraction=eig/eig.sum();ax.bar(np.arange(1,n+1),fraction*100);ax.set(xlabel='Principal component',ylabel='Explained variance (%)');save(['component','variance','fraction'],np.arange(1,n+1),eig,fraction)
            else:
                out=np.full(z.shape,np.nan);out[mask]=vec[:,0]@centered;show(out,'Centered PC1 score','RdBu_r')
                meta['loadings']=vec[:,0].tolist()
            meta['used_count']=int(mask.sum())
        else:
            if kind=='spectral_angle':
                ref=a.mean(axis=1);cos=safe_ratio(ref@a,np.linalg.norm(ref)*np.linalg.norm(a,axis=0));v=np.degrees(np.arccos(np.clip(cos,-1,1)))
            elif kind=='spectral_ratio':v=safe_ratio(a[0],a[1])
            elif kind=='spectral_savi':v=(1+parameter)*safe_ratio(a[0]-a[1],a[0]+a[1]+parameter)
            elif kind=='spectral_evi':v=2.5*safe_ratio(a[0]-a[1],a[0]+6*a[1]-7.5*a[2]+1)
            else:v=safe_ratio(a[0]-a[1],a[0]+a[1])
            out=np.full(z.shape,np.nan);out[mask]=v;show(out,'Angle (degrees)' if kind=='spectral_angle' else 'Index (unitless)','RdBu_r' if kind not in {'spectral_angle','spectral_ratio'} else None,output_unit='degree' if kind=='spectral_angle' else 'unitless')
    elif kind.startswith('ensemble_'):
        stack,mask=aligned_grids(grids);a=stack[:,mask]
        if kind=='ensemble_mean':v=a.mean(axis=0)
        elif kind=='ensemble_median':v=np.median(a,axis=0)
        elif kind=='ensemble_iqr':v=np.quantile(a,.75,axis=0)-np.quantile(a,.25,axis=0)
        elif kind in {'ensemble_lower','ensemble_upper'}:v=np.quantile(a,parameter,axis=0)
        elif kind=='ensemble_cv':v=safe_ratio(a.std(axis=0,ddof=1),np.abs(a.mean(axis=0)))
        elif kind=='ensemble_range':v=np.ptp(a,axis=0)
        else:v=np.maximum((a>0).mean(axis=0),(a<0).mean(axis=0))
        out=np.full(z.shape,np.nan);out[mask]=v;show(out,'Fraction' if kind in {'ensemble_cv','ensemble_sign'} else unit,output_unit='unitless' if kind in {'ensemble_cv','ensemble_sign'} else g.unit)
        meta['realizations']=len(grids)
    elif kind.startswith('land_'):
        require(g.is_meter,'Land-cover area and patch analysis requires a projected metre grid.')
        finite=np.isfinite(z);classes=np.unique(z[finite]);require(len(classes)<=24,'Maximum 24 class codes.')
        area=g.transform.a*(-g.transform.e)
        if kind in {'land_transition','land_transition_map','land_gain_loss'}:
            require(len(grids)==2,'Select baseline and candidate class rasters.')
            a,mask=aligned_grids(grids);classes=np.unique(a[:,mask]);require(len(classes)<=24,'Maximum 24 class codes.')
            i,j=np.searchsorted(classes,a[:,mask]);mat=np.zeros((len(classes),len(classes)),dtype=np.int64);np.add.at(mat,(i,j),1)
            meta['used_count']=int(mask.sum());meta['class_codes']=classes.tolist()
            if kind=='land_transition':
                im=ax.imshow(mat*area/1e6,cmap=cmap);fig.colorbar(im,ax=ax,label='Area (km²)')
                ax.set_xticks(range(len(classes)),[str(c) for c in classes],rotation=45);ax.set_yticks(range(len(classes)),[str(c) for c in classes]);ax.set(xlabel='Candidate class',ylabel='Baseline class')
                derived.extend([['baseline_class','candidate_class','cells','area_m2'],*[[float(c),float(d),int(mat[i,j]),float(mat[i,j]*area)] for i,c in enumerate(classes) for j,d in enumerate(classes)]])
            elif kind=='land_gain_loss':
                gain=(mat.sum(axis=0)-mat.diagonal())*area;loss=(mat.sum(axis=1)-mat.diagonal())*area
                ax.bar(np.arange(len(classes)),gain/1e6,label='Gain');ax.bar(np.arange(len(classes)),-loss/1e6,label='Loss');ax.set_xticks(range(len(classes)),classes);ax.set_ylabel('Area (km²)');ax.legend(frameon=False);save(['class','gain_m2','loss_m2'],classes,gain,loss)
            else:
                out=np.full(z.shape,np.nan);out[mask]=(i!=j).astype(float);show(out,'Changed (1) / stable (0)','viridis',0,1)
        elif kind=='land_class_area':
            counts=np.array([(z==c).sum() for c in classes]);ax.bar(range(len(classes)),counts*area/1e6);ax.set_xticks(range(len(classes)),classes);ax.set(xlabel='Class code',ylabel='Area (km²)');save(['class','cells','area_m2'],classes,counts,counts*area)
        elif kind=='land_edge_density':
            edge=np.zeros(z.shape);n=np.zeros(z.shape)
            for v in neighbors(z):
                valid=finite&np.isfinite(v);edge+=valid&(v!=z);n+=valid
            show(np.where(finite,safe_ratio(edge,n),np.nan),'Fraction of cardinal edges crossing class boundary',vmin=0,vmax=1)
        elif kind=='land_local_diversity':
            n=np.zeros(z.shape);counts=np.zeros((len(classes),*z.shape),dtype=np.uint8)
            for v in [z,*neighbors(z,True)]:
                n+=np.isfinite(v)
                for i,c in enumerate(classes):counts[i]+=v==c
            entropy=np.zeros(z.shape)
            for c in counts:
                p=safe_ratio(c.astype(float),n);valid=p>0;entropy[valid]-=p[valid]*np.log(p[valid])
            entropy[~finite]=np.nan;show(entropy,'Local Shannon entropy (nats)')
        else:
            labels,sizes,codes=patch_labels(z);meta['patches']=len(sizes)
            if kind=='land_patch_map':show(np.where(finite,labels.astype(float),np.nan),'Patch identifier')
            else:
                ax.hist(sizes*area/1e6,bins=min(30,max(2,len(sizes))));ax.set(xlabel='Patch area (km²)',ylabel='Patch count')
                if len(sizes)<=20000:save(['patch_id','class','cells','area_m2'],np.arange(1,len(sizes)+1),codes,sizes,sizes*area)
    elif kind.startswith('terrain_'):
        require(g.is_meter and unit in {'m','meter','metre'},'Terrain derivatives require a projected metre grid and metre elevation.')
        require(min(z.shape)>=3,'Terrain derivatives require at least 3 × 3 cells.')
        if kind in {'terrain_tpi','terrain_tri','terrain_roughness','terrain_relief_curve'}:
            mean,sd,span,rms,_=local_moments(z,True)
            if kind=='terrain_tpi':show(z-mean,'Elevation minus eight-neighbor mean (m)','RdBu_r',output_unit='m')
            elif kind=='terrain_tri':show(rms,'RMS neighbor elevation difference (m)',output_unit='m')
            elif kind=='terrain_roughness':show(span,'Eight-neighbor elevation range (m)',output_unit='m')
            else:
                valid=np.isfinite(z)&np.isfinite(span);v=z[valid];r=span[valid];require(v.size>0 and np.ptp(v)>0,'Relief curve needs varying elevation.')
                edges=np.linspace(v.min(),v.max(),int(parameter)+1);idx=np.clip(np.searchsorted(edges,v,side='right')-1,0,len(edges)-2)
                centers=(edges[:-1]+edges[1:])/2;counts=np.bincount(idx,minlength=len(centers));means=safe_ratio(np.bincount(idx,weights=r,minlength=len(centers)),counts.astype(float))
                ax.plot(centers,means,marker='o');ax.set(xlabel='Elevation (m)',ylabel='Mean neighborhood range (m)');save(['elevation_mid_m','cells','mean_relief_m'],centers,counts,means);meta['used_count']=int(v.size)
        else:
            dy,dx=np.gradient(z,g.transform.e,g.transform.a);valid=np.isfinite(z)&np.isfinite(dx)&np.isfinite(dy)
            if kind=='terrain_aspect_map':
                out=(np.degrees(np.arctan2(-dx,-dy))+360)%360;out[~valid|(np.hypot(dx,dy)==0)]=np.nan;show(out,'Downhill bearing (degrees)','twilight',0,360,output_unit='degree')
            elif kind=='terrain_gradient_east':show(np.where(valid,dx,np.nan),'East gradient (m/m)','RdBu_r')
            elif kind=='terrain_gradient_north':show(np.where(valid,dy,np.nan),'North gradient (m/m)','RdBu_r')
            elif kind=='terrain_surface_ratio':show(np.where(valid,np.sqrt(1+dx*dx+dy*dy),np.nan),'Local planar surface / horizontal area')
            else:
                _,dxx=np.gradient(dx,g.transform.e,g.transform.a);dyy,_=np.gradient(dy,g.transform.e,g.transform.a);show(np.where(valid,dxx+dyy,np.nan),'Elevation Laplacian (1/m)','RdBu_r')
    elif kind in {'spatial_relative_change','spatial_absolute_change','spatial_z_change','spatial_rmse_tiles','spatial_mae_tiles'}:
        require(len(grids)==(3 if kind=='spatial_z_change' else 2),'Select baseline, candidate and, for standardized change, difference SD.')
        stack,mask=aligned_grids(grids);d=np.where(mask,stack[1]-stack[0],np.nan)
        if kind=='spatial_relative_change':show(100*safe_ratio(d,np.abs(stack[0])),'Relative change (%)','RdBu_r')
        elif kind=='spatial_absolute_change':show(np.abs(d),'Absolute difference ('+unit+')',output_unit=g.unit)
        elif kind=='spatial_z_change':
            require(np.all(stack[2][mask]>=0),'Difference SD cannot be negative.');show(safe_ratio(d,stack[2]),'Difference / supplied SD','RdBu_r')
        else:
            v=d*d if kind=='spatial_rmse_tiles' else np.abs(d);m,_,_,_,_=local_moments(v,True);show(np.sqrt(m) if kind=='spatial_rmse_tiles' else m,('Neighborhood RMSE' if kind=='spatial_rmse_tiles' else 'Neighborhood MAE')+' ('+unit+')')
    elif kind.startswith('spatial_'):
        if kind in {'spatial_variogram','spatial_covariogram','spatial_correlogram'}:
            require(g.is_meter,'Metric lag analysis requires projected metre coordinates.')
            require(float(parameter).is_integer(),'Maximum lag must be an integer.')
            mu=np.nanmean(z);rows=[]
            for direction,spacing,grid in [('East',g.transform.a,z),('North',-g.transform.e,z.T)]:
                for lag in range(1,min(int(parameter),grid.shape[1]-1)+1):
                    a=grid[:,:-lag];b=grid[:,lag:];valid=np.isfinite(a)&np.isfinite(b);a=a[valid];b=b[valid]
                    if len(a)<2:continue
                    if kind=='spatial_variogram':value=np.mean((a-b)**2)/2
                    elif kind=='spatial_covariogram':value=np.mean((a-mu)*(b-mu))
                    else:
                        if a.std()==0 or b.std()==0:continue
                        value=np.corrcoef(a,b)[0,1]
                    rows.append((direction,lag*spacing,len(a),float(value)))
            require(rows,'No valid directional lag pairs.')
            for direction in ('East','North'):
                selected=[r for r in rows if r[0]==direction]
                if selected:ax.plot([r[1] for r in selected],[r[3] for r in selected],marker='o',label=direction)
            ax.legend(frameon=False);ax.set(xlabel='Lag (m)',ylabel={'spatial_variogram':'Semivariance','spatial_covariogram':'Covariance','spatial_correlogram':'Correlation'}[kind]);derived.extend([['direction','lag_m','pairs','statistic'],*map(list,rows)])
        else:
            mean,sd,span,rms,count=local_moments(z)
            if kind=='spatial_local_mean':show(mean,unit,output_unit=g.unit)
            elif kind=='spatial_local_sd':show(sd,'Neighbor population SD ('+unit+')',output_unit=g.unit)
            elif kind=='spatial_local_range':show(span,'Neighbor range ('+unit+')',output_unit=g.unit)
            elif kind=='spatial_local_z':show(safe_ratio(z-mean,sd),'Local standardized anomaly','RdBu_r')
            else:
                std=np.nanstd(z);require(std>0,'Spatial standardized statistics need varying data.')
                u=(z-np.nanmean(z))/std;lag,_,_,rms,_=local_moments(u)
                if kind=='spatial_local_moran':
                    view=req.spatial_inference
                    if view=='statistic':show(u*lag,'Local Moran I','RdBu_r',output_unit='unitless')
                    else:
                        from .studio_inference import conditional_moran
                        p,q=conditional_moran(u,lag,count,req.permutations,req.random_seed)
                        meta.update(permutations=req.permutations,seed=req.random_seed,alpha=req.alpha,
                            inference='Conditional randomization of other valid cells under exchangeability; BY adjustment across all tested cells.',
                            tested_cells=int(np.isfinite(p).sum()),significant_cells=int((q<=req.alpha).sum()),minimum_p=1/(req.permutations+1))
                        if view=='p':show(p,'Conditional Monte Carlo p',vmin=0,vmax=1,output_unit='probability')
                        elif view=='q':show(q,'BY-adjusted p',vmin=0,vmax=1,output_unit='probability')
                        else:
                            codes=np.where(np.isfinite(q),0.,np.nan);significant=q<=req.alpha
                            codes[significant&(u>0)&(lag>0)]=1;codes[significant&(u<0)&(lag<0)]=2
                            codes[significant&(u>0)&(lag<0)]=3;codes[significant&(u<0)&(lag>0)]=4
                            show(codes,'0 not significant; 1 HH; 2 LL; 3 HL; 4 LH',ListedColormap(['#eeeeee','#b33637','#3663a1','#e29e51','#7b75b4']),-.5,4.5,output_unit='class')
                elif kind=='spatial_geary':show(rms*rms,'Local mean squared standardized difference')
                else:
                    valid=np.isfinite(u)&np.isfinite(lag);x=u[valid];y=lag[valid];require(x.size>1,'No valid spatial lag pairs.')
                    stride=max(1,int(np.ceil(len(x)/2000)));ax.scatter(x[::stride],y[::stride],s=5,alpha=.5);ax.axhline(0,color='gray');ax.axvline(0,color='gray')
                    slope=float(x@y/(x@x)) if x@x>0 else 0
                    xx=np.array([x.min(),x.max()]);ax.plot(xx,slope*xx);ax.set(xlabel='Standardized observation',ylabel='Row-standardized spatial lag')
                    meta.update(used_count=int(len(x)),plotted_count=int(len(x[::stride])),moran_I=slope,sampling='systematic display sample; statistic uses all paired cells')
                    save(['standardized_value','spatial_lag'],x[::stride],y[::stride])
    else:raise FigureInputError('Unimplemented raster domain recipe.')
    return derived
