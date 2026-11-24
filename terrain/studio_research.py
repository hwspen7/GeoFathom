"""Publication-oriented visual diagnostics from recorded scientific products.

No fitting of unavailable measurements, hidden interpolation or synthetic points.
"""
import numpy as np
from .studio_data import FigureInputError,aligned_grids
from .studio_publication import numeric_rows

RECIPES=(
 ('research_agreement','Paired validation and Bland–Altman diagnostics','Research validation','table','x y'),
 ('research_ecdf','Group empirical cumulative distributions','Research validation','table','y group'),
 ('research_qq','Paired empirical quantile comparison','Research validation','table','x y'),
 ('research_forest','Effect estimates with supplied intervals','Research validation','table','x y low high'),
 ('research_taylor','Centered Taylor model comparison','Research validation','table','x columns'),
 ('research_time_fan','Nested supplied prediction interval fan','Time series','table','x y columns'),
 ('research_spacetime_lag','Native space-time lag matrix and pair support','Time series','table','x y z columns'),
 ('research_map_distribution','Native raster map and distribution','Cartography','raster',''),
 ('research_map_agreement','Aligned raster agreement dashboard','Cartography','raster',''),
 ('research_map_bivariate','Bivariate classified native raster map','Cartography','raster',''),
 ('research_map_change','Baseline, candidate and signed change atlas','Cartography','raster',''),
)
IDS={r[0] for r in RECIPES}
MIN_RASTERS={k:2 for k in ('research_map_agreement','research_map_bivariate','research_map_change')}
NOTES={
 'research_agreement':'X reference, Y comparison. Bias and descriptive normal-reference limits of agreement (not confidence intervals).',
 'research_ecdf':'Independent valid observations by group; no distribution fit or significance claim.',
 'research_qq':'Paired complete observations, common empirical quantile probabilities; not a goodness-of-fit test.',
 'research_forest':'X effect label, Y estimate, low/high supplied interval endpoints; not inferred meta-analysis.',
 'research_taylor':'X reference, columns model predictions; all series share complete cases. Centered RMSE, correlation and SD.',
 'research_time_fan':'X time, Y estimate, columns ordered outer lower, outer upper, inner lower, inner upper; supplied intervals, no inferred coverage.',
 'research_spacetime_lag':'X spatial lag, Y temporal lag, Z semivariance, one selected column for valid pair count. No interpolation; missing bins masked.',
 'research_map_distribution':'Native cells, NoData retained; histogram counts are cells, not independent samples.',
 'research_map_agreement':'Two aligned rasters of the same physical unit; common-cell residual map, paired density and descriptive agreement statistics.',
 'research_map_bivariate':'Two aligned rasters; each classified by observed tertiles on common valid cells. Different units allowed; no causal inference.',
 'research_map_change':'Baseline and candidate share physical unit and grid, identical common mask and color limits; candidate minus baseline.',
}
def require(ok,msg):
    if not ok:raise FigureInputError(msg)

def agreement(x,y):
    require(len(x)>=3,'At least three paired observations required.')
    delta=y-x;mean=(x+y)/2;bias=float(delta.mean());sd=float(delta.std(ddof=1))
    return mean,delta,{'pairs':len(x),'bias':bias,'mae':float(abs(delta).mean()),'rmse':float(np.sqrt(np.mean(delta**2))),
        'difference_sd':sd,'lower_agreement':bias-1.96*sd,'upper_agreement':bias+1.96*sd}

def matrix_lags(x,y,z,n):
    require(len(set(zip(x,y)))==len(x),'Duplicate space-time lag bins.')
    require(np.all(x>=0) and np.all(y>=0) and np.all(z>=0) and np.all(n>0) and np.all(n==np.floor(n)),'Invalid lag, semivariance or pair count.')
    xs=np.unique(x);ys=np.unique(y);require(2<=len(xs)<=100 and 2<=len(ys)<=100,'Need 2–100 distinct lags per dimension.')
    a=np.full((len(ys),len(xs)),np.nan);b=a.copy()
    i=np.searchsorted(ys,y);j=np.searchsorted(xs,x);a[i,j]=z;b[i,j]=n
    return xs,ys,a,b

def render_table(kind,req,fig,ax,table,meta,palette,rows):
    from matplotlib.colors import Normalize
    from .studio_publication import cell_edges
    def pair():return rows([req.x,req.y])[0]
    def save(h,*a):return numeric_rows(h,*a)
    color=palette[0]
    if kind=='research_agreement':
        x,y=pair();m,d,stats=agreement(x,y);meta.update(stats)
        fig.delaxes(ax);a,b=fig.subplots(1,2)
        lo=min(x.min(),y.min());hi=max(x.max(),y.max())
        im=a.hexbin(x,y,gridsize=28,mincnt=1,cmap='viridis');fig.colorbar(im,ax=a,label='Pair count',shrink=.8);a.plot([lo,hi],[lo,hi],'--',color='#444444');a.set(xlabel=req.x,ylabel=req.y,title='Paired observations',aspect='equal')
        b.scatter(m,d,s=9,color=color,alpha=.5,rasterized=len(m)>5000)
        for v,ls in [(stats['bias'],'-'),(stats['lower_agreement'],'--'),(stats['upper_agreement'],'--')]:b.axhline(v,color='#555555',linestyle=ls,linewidth=.8)
        b.set(xlabel='Pair mean',ylabel='Comparison − reference',title='Bland–Altman')
        return save([req.x,req.y,'pair_mean','difference'],x,y,m,d)
    if kind=='research_ecdf':
        (y,), (g,)=rows([req.y],[req.group]);keys=sorted(set(g));require(len(keys)<=12,'At most 12 groups.')
        data=[['group','value','ecdf']]
        for i,k in enumerate(keys):
            a=np.sort(y[g==k]);p=np.arange(1,len(a)+1)/len(a)
            ax.step(a,p,where='post',label=k,color=palette[i%len(palette)],linestyle=['-','--',':','-.'][i%4]);data.extend(save(['group','value','ecdf'],[k]*len(a),a,p)[1:])
        ax.set(xlabel=req.y,ylabel='Empirical cumulative probability',ylim=(0,1.02));ax.legend()
        return data
    if kind=='research_qq':
        x,y=pair();p=np.linspace(0,1,min(201,len(x)));a=np.quantile(x,p);b=np.quantile(y,p)
        ax.scatter(a,b,s=12,color=color);lo=min(a.min(),b.min());hi=max(a.max(),b.max());ax.plot([lo,hi],[lo,hi],'--',color='#555555');ax.set(xlabel=req.x+' quantile',ylabel=req.y+' quantile',aspect='equal')
        return save(['probability','reference_quantile','comparison_quantile'],p,a,b)
    if kind=='research_forest':
        (y,lo,hi),(g,)=rows([req.y,req.low,req.high],[req.x]);require(len(y)<=40 and np.all(lo<=y) and np.all(y<=hi),'At most 40 effects, each with ordered bounds containing its estimate.')
        i=np.arange(len(y));ax.errorbar(y,i,xerr=[y-lo,hi-y],fmt='o',color=color,capsize=2);ax.set_yticks(i,g);ax.invert_yaxis();ax.set_xlabel(req.y)
        if min(lo)<=0<=max(hi):ax.axvline(0,color='#777777',linestyle='--',linewidth=.8)
        return save([req.x,req.y,req.low,req.high],g,y,lo,hi)
    if kind=='research_taylor':
        require(1<=len(req.columns)<=8 and req.x not in req.columns,'Choose one reference and one to eight distinct predictions.')
        data,_=rows([req.x,*req.columns]);ref=data[0];sd=float(ref.std(ddof=1));require(len(ref)>=3 and sd>0,'Nonconstant reference with at least three complete pairs required.')
        fig.delaxes(ax);ax=fig.add_subplot(111,projection='polar');records=[]
        for i,(name,v) in enumerate(zip(req.columns,data[1:])):
            s=float(v.std(ddof=1));require(s>0,'Constant prediction cannot be positioned on a Taylor diagram.')
            r=float(np.clip(np.corrcoef(ref,v)[0,1],-1,1));cr=float(np.sqrt(np.mean(((v-v.mean())-(ref-ref.mean()))**2)*len(ref)/(len(ref)-1)))
            ax.scatter(np.arccos(r),s,s=32,label=name,color=palette[i%len(palette)]);records.append([name,r,s,cr])
        ax.scatter(0,sd,marker='*',s=64,color='#222222',label='Reference');ax.set_thetamin(0);ax.set_thetamax(180)
        limit=max(sd,max(r[2] for r in records))*1.15;theta=np.linspace(0,np.pi,181);rad=np.linspace(0,limit,100);T,R=np.meshgrid(theta,rad);err=np.sqrt(np.maximum(0,sd*sd+R*R-2*sd*R*np.cos(T)));contour=ax.contour(T,R,err,levels=5,colors='#808080',linewidths=.55,linestyles='dotted');ax.clabel(contour,fontsize=7,fmt='%.2g');ax.set_ylim(0,limit)
        ticks=np.array([1,.9,.7,.5,0,-.5,-1]);ax.set_xticks(np.arccos(ticks),[str(v) for v in ticks]);ax.set_ylabel('Sample SD');ax.legend(loc='upper right',bbox_to_anchor=(1.2,1.12))
        meta['reference_sd']=sd
        return [['model','correlation','sample_sd','centered_rmse'],*records]
    if kind=='research_time_fan':
        require(len(req.columns)==4 and len(set([req.x,req.y,*req.columns]))==6,'Select four distinct interval columns in outer then inner order.')
        x=table.numeric(req.x);y=table.numeric(req.y);outerlo,outerhi,innerlo,innerhi=[table.numeric(k) for k in req.columns]
        require(np.isfinite(x).all() and np.all(np.diff(x)>0),'Time coordinates must be strictly increasing.')
        ok=np.isfinite(y)&np.isfinite(outerlo)&np.isfinite(outerhi)&np.isfinite(innerlo)&np.isfinite(innerhi)
        require(ok.any() and np.all((outerlo[ok]<=innerlo[ok])&(innerlo[ok]<=y[ok])&(y[ok]<=innerhi[ok])&(innerhi[ok]<=outerhi[ok])),'Supplied intervals must be nested around the estimate.')
        ax.fill_between(x,outerlo,outerhi,where=ok,color=color,alpha=.15,label='Outer supplied interval');ax.fill_between(x,innerlo,innerhi,where=ok,color=color,alpha=.32,label='Inner supplied interval');ax.plot(x,y,color=color,label='Estimate');ax.legend();ax.set(xlabel=req.x,ylabel=req.y);meta['used_count']=int(np.isfinite(y).sum())
        return save([req.x,req.y,*req.columns],x,y,outerlo,outerhi,innerlo,innerhi)
    if kind=='research_spacetime_lag':
        require(len(req.columns)==1,'Select the valid-pair count column.')
        (x,y,z,n),_=rows([req.x,req.y,req.z,req.columns[0]]);xs,ys,a,b=matrix_lags(x,y,z,n)
        fig.delaxes(ax);axes=fig.subplots(1,2,sharex=True,sharey=True)
        for target,v,title in zip(axes,[a,b],['Semivariance','Valid pair count']):
            # Actual nonuniform bin spacing retained by explicit cell edges.
            im=target.pcolormesh(cell_edges(xs),cell_edges(ys),v,cmap='viridis',shading='flat');fig.colorbar(im,ax=target,shrink=.85);target.set(xlabel=req.x,title=title)
        axes[0].set_ylabel(req.y);meta['missing_bins']=int(np.isnan(a).sum())
        return save([req.x,req.y,req.z,req.columns[0]],x,y,z,n)
    raise FigureInputError('Unknown research table recipe.')

def render_raster(kind,req,fig,ax,grids,meta):
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MaxNLocator
    g=grids[0];unit=g.unit or 'unit unspecified';z=g.values
    def draw(target,a,title,cm=None,lo=None,hi=None,colorbar=True):
        from matplotlib import colormaps
        cm=colormaps[cm or (req.sequential_cmap if req.sequential_cmap!='default' else 'viridis')].copy();cm.set_bad('#dedede')
        im=target.imshow(a,extent=g.extent,origin='upper',interpolation='nearest',cmap=cm,vmin=lo,vmax=hi)
        target.set(title=title,aspect='equal',xlabel='Easting' if g.crs.is_projected else 'Longitude / x',ylabel='Northing' if g.crs.is_projected else 'Latitude / y')
        target.ticklabel_format(style='plain',useOffset=False);target.xaxis.set_major_locator(MaxNLocator(3));target.yaxis.set_major_locator(MaxNLocator(3))
        if req.map_decoration=='minimal':target.set(xlabel='',ylabel='',xticks=[],yticks=[])
        if colorbar:fig.colorbar(im,ax=target,shrink=.78,label=unit)
        return im
    if kind=='research_map_distribution':
        require(len(grids)==1,'Select exactly one raster.');v=z[np.isfinite(z)];fig.delaxes(ax);a,b=fig.subplots(1,2)
        draw(a,z,g.name);counts,edges=np.histogram(v,bins=min(40,max(5,int(np.sqrt(len(v))))));b.stairs(counts,edges,fill=True,color='#0072B2',alpha=.7);b.set(xlabel=unit,ylabel='Native cell count',title='Distribution')
        meta.update(valid_cells=int(len(v)),nodata_cells=int(z.size-len(v)),median=float(np.median(v)))
        return numeric_rows(['lower_edge','upper_edge','cells'],edges[:-1],edges[1:],counts)
    require(len(grids)==2,'Select exactly two rasters.')
    stack,common=aligned_grids(grids, require_same_unit=kind!='research_map_bivariate')
    x,y=stack[:,common];meta.update(used_count=int(common.sum()),common_valid_cells=int(common.sum()))
    if kind=='research_map_bivariate':
        cuts=[np.quantile(v,[1/3,2/3]) for v in (x,y)];require(all(v[0]<v[1] for v in cuts),'Distinct tertile breaks required.')
        codes=np.searchsorted(cuts[0],x,side='right')+3*np.searchsorted(cuts[1],y,side='right')
        out=np.full(z.shape,np.nan);out[common]=codes
        palette=['#e8e8e8','#ace4e4','#5ac8c8','#dfb0d6','#a5add3','#5698b9','#be64ac','#8c62aa','#3b4994']
        fig.delaxes(ax);a,b=fig.subplots(1,2,gridspec_kw={'width_ratios':[2,1]})
        cm=ListedColormap(palette);cm.set_bad('#dedede');a.imshow(out,extent=g.extent,origin='upper',interpolation='nearest',cmap=cm,norm=BoundaryNorm(np.arange(10)-.5,9));a.set_aspect('equal');a.set_title('Bivariate tertile classes');a.ticklabel_format(style='plain',useOffset=False)
        a.set_xlabel('Easting' if g.crs.is_projected else 'Longitude / x');a.set_ylabel('Northing' if g.crs.is_projected else 'Latitude / y');a.xaxis.set_major_locator(MaxNLocator(3));a.yaxis.set_major_locator(MaxNLocator(3))
        if req.map_decoration=='minimal':a.set(xlabel='',ylabel='',xticks=[],yticks=[])
        for j in range(3):
            for i in range(3):b.add_patch(Rectangle((i,j),1,1,color=palette[i+3*j]))
        b.set(xlim=(0,3),ylim=(0,3),aspect='equal',xlabel=grids[0].name,ylabel=grids[1].name);b.set_xticks([.5,1.5,2.5],['Low','Mid','High']);b.set_yticks([.5,1.5,2.5],['Low','Mid','High'])
        meta['tertile_breaks']=[a.tolist() for a in cuts];return [['class_x','class_y','cells'],*[[i+1,j+1,int(np.sum(codes==i+3*j))] for j in range(3) for i in range(3)]]
    m,d,stats=agreement(x,y);meta.update(stats)
    a0=np.where(common,stack[0],np.nan);a1=np.where(common,stack[1],np.nan);delta=a1-a0;lim=max(float(np.max(abs(d))),1e-12)
    fig.delaxes(ax)
    if kind=='research_map_change':
        a,b,c=fig.subplots(1,3,sharex=True,sharey=True)
        lo=min(x.min(),y.min());hi=max(x.max(),y.max());im=draw(a,a0,grids[0].name,lo=lo,hi=hi,colorbar=False);draw(b,a1,grids[1].name,lo=lo,hi=hi,colorbar=False);fig.colorbar(im,ax=[a,b],shrink=.78,label=unit);draw(c,delta,'Candidate − baseline','RdBu_r',-lim,lim)
    else:
        a,b=fig.subplots(1,2);draw(a,delta,'Candidate − reference','RdBu_r',-lim,lim)
        im=b.hexbin(x,y,gridsize=35,mincnt=1,bins='log',cmap='viridis');fig.colorbar(im,ax=b,label='Cell count',shrink=.78);lo=min(x.min(),y.min());hi=max(x.max(),y.max());b.plot([lo,hi],[lo,hi],'--',color='#555555');b.set(xlabel=grids[0].name,ylabel=grids[1].name,aspect='equal',title='Paired native cells')
    return [['metric','value'],*[[k,v] for k,v in stats.items()]]
