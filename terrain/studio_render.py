"""Matplotlib-backed scientific plotting. Never synthesize missing observations."""
from __future__ import annotations
import io
import math
import threading
import numpy as np
from .studio_catalog import BY_ID, NOTES, OPTIONS, MIN_RASTERS
from .studio_domain_catalog import IDS as DOMAIN_IDS
from .studio_data import (Table, read_grids, aligned_grids, normalized, pareto_mask, average_rank,
                          regular_series, rectangular_grid, linear_fit, sobol_indices, morris_effects,
                          FigureInputError)

LOCK=threading.RLock()
COLORS=['#0072B2','#D55E00','#009E73','#CC79A7','#E69F00','#56B4E9','#6B4C9A','#555555']
MARKERS=['o','s','^','D','v','P','X','+']

def _require(condition,message):
    if not condition:raise FigureInputError(message)

from .studio_publication import (response_grid, cell_edges, profile_data, raster_profiles,
                                 numeric_rows, layout_receipt, fit_publication_text, publication_title)

def render(req, container=None, panel_label='', grid_sink=None):
    from matplotlib.figure import Figure
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import ListedColormap,BoundaryNorm,to_hex
    from matplotlib import colormaps
    from matplotlib.patches import Patch
    from matplotlib.ticker import MaxNLocator
    from matplotlib.colors import LightSource
    recipe=BY_ID.get(req.recipe)
    _require(recipe is not None,'Unknown figure recipe.')
    kind,title,_,source,fields=recipe
    option=OPTIONS.get(kind)
    parameter=req.parameter if req.parameter is not None else option[1] if option else 0
    if option:_require(option[2]<=parameter<=option[3],'Figure parameter outside allowed range.')
    for name in fields.split():
        _require(bool(getattr(req,name)),'Select required field: '+name)
    _require(len(set(req.columns))==len(req.columns),'Select distinct columns.')
    table=Table(req.csv) if source=='table' else None
    grids=read_grids(req.rasters) if source=='raster' else []
    if grids:_require(len(grids)>=MIN_RASTERS.get(kind,1),'Select the required number of rasters.')
    if grids and kind not in DOMAIN_IDS and kind not in {'raster_matrix','raster_uncertainty','raster_exceedance','raster_difference','raster_significant_change','raster_profile'}:_require(len(grids)==1,'This recipe requires exactly one raster.')
    if source=='raster':_require(bool(grids),'Select GeoTIFF input.')
    count=len(table.rows) if table else int(np.isfinite(grids[0].values).sum())
    meta={'recipe':kind,'method_note':NOTES.get(kind,''),'input_count':count,'used_count':count,
          'raster_sources':[{'name':g.name,'sha256':g.sha256,'crs':str(g.crs),'unit':g.unit,'shape':list(g.values.shape),'band':g.band,'band_count':g.band_count,'scale':g.scale,'offset':g.offset} for g in grids]}
    derived=[]
    def rows(names,labels=()):
        nonlocal count
        arrays,cats,count=table.aligned(names,labels);meta['used_count']=count
        return arrays,cats
    def xy():
        a,_=rows([req.x,req.y]);return a
    def grouped():
        a,c=rows([req.y],[req.group]);v=a[0];g=c[0]
        keys=list(dict.fromkeys(g))
        _require(len(keys)<=24,'Maximum 24 groups.')
        return keys,[v[g==k] for k in keys]
    def save_rows(headers,*arrays):
        derived.clear();derived.extend(numeric_rows(headers,*arrays))
    # Every recipe reports its actual source and selection contract.
    meta.update(family=recipe[2],source_type=source,required_fields=fields.split(),software={'numpy':np.__version__,'matplotlib':__import__('matplotlib').__version__})
    palette=COLORS if req.palette!='mono' else ['#1e1e1e','#777777','#a0a0a0','#4e4e4e','#b4b4b4','#333333','#8d8d8d','#555555']
    cmap={'mono':'Greys','earth':'terrain','color':'viridis'}[req.palette]
    color=palette[0]
    rc={'font.family':'serif' if req.font=='serif' else 'sans-serif','font.size':req.font_size,
        'axes.labelsize':req.font_size,'xtick.labelsize':max(6,req.font_size-1),'ytick.labelsize':max(6,req.font_size-1),
        'legend.fontsize':max(6,req.font_size-1),'legend.frameon':False,'axes.linewidth':.75,
        'axes.axisbelow':True,'grid.linewidth':.55,'xtick.major.width':.75,'ytick.major.width':.75,
        'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'normal',
        'svg.fonttype':'none','pdf.fonttype':42,'lines.linewidth':req.line_width,'axes.prop_cycle':__import__('cycler').cycler(color=palette)}
    with LOCK,rc_context(rc):
        fig=container if container is not None else Figure(figsize=(req.width_mm/25.4,req.height_mm/25.4),layout='constrained',facecolor='white')
        if container is None:FigureCanvasAgg(fig)
        is3d=(kind=='response_surface' and req.response_style=='surface') or kind in {'terrain_surface','terrain_wireframe','scatter_3d'}
        ax=fig.add_subplot(111,projection='3d' if is3d else 'polar' if kind=='radar' else None)
        xlabel=req.x or '';ylabel=req.y or ''
        if kind in DOMAIN_IDS:
            if source=='raster':
                from .studio_domain_raster import render_raster_domain
                if MIN_RASTERS.get(kind,1)==1:_require(len(grids)==1,'Select exactly one raster for this recipe.')
                derived=render_raster_domain(kind,req,fig,ax,grids,parameter,meta,cmap,grid_sink)
            else:
                from .studio_domain_table import render_table_domain
                derived=render_table_domain(kind,req,fig,ax,table,parameter,meta,palette,cmap,rows)
            # Domain renderers specify labels for the computed quantities.
            # Respect explicit overrides on the surviving primary axes.
            if ax in fig.axes:
                if req.x_label:ax.set_xlabel(req.x_label)
                if req.y_label:ax.set_ylabel(req.y_label)
                if source=='table' and ax.name!='polar':ax.grid(req.grid,alpha=.16)
            ax=None
        elif kind in {'multi_line','grouped_bar','stacked_bar'}:
            _require(2<=len(req.columns)<=12,'Choose two to twelve series.')
            if kind=='multi_line':
                if req.profile_style=='series':
                    # Independent finite masks preserve the observations of each line.
                    x=table.numeric(req.x);_require(np.isfinite(x).all(),'X coordinates cannot be missing.')
                    order=np.argsort(x,kind='stable');x=x[order];a=np.stack([table.numeric(n)[order] for n in req.columns]);names=req.columns
                    _require(np.isfinite(a).any(),'No finite series observations.')
                else:x,a,names=profile_data(table,req.x,req.columns,req.profile_style)
                if req.profile_style=='bands':
                    for i in range(0,len(names),3):
                        mean,lo,hi=a[i:i+3];ink=palette[(i//3)%8]
                        mask=np.isfinite(mean)&np.isfinite(lo)&np.isfinite(hi)
                        ax.fill_between(x,lo,hi,where=mask,color=ink,alpha=.2)
                        ax.plot(x,mean,color=ink,label=names[i],linewidth=req.line_width)
                    meta['interval_note']='Supplied pointwise intervals, not inferred confidence or simultaneous bounds.'
                else:
                    for i,(name,y) in enumerate(zip(names,a)):
                        ax.plot(x,y,label=name,color=palette[i%8],linestyle=['-','--','-.',':'][i%4],linewidth=req.line_width,marker=MARKERS[i%8] if req.show_points else None,markersize=3)
                    if req.profile_style=='delta':ax.axhline(0,color='#666666',linewidth=.8)
                derived.extend(numeric_rows([req.x,*names],x,*a))
                meta.update(used_count=int(np.any(np.isfinite(a),axis=0).sum()),series_valid_counts=[int(np.isfinite(v).sum()) for v in a],profile_style=req.profile_style)
                ylabel='Difference from baseline' if req.profile_style=='delta' else 'Value (compatible units)'
            else:
                a,c=rows(req.columns,[req.x]);labels=c[0];_require(len(labels)<=60,'Maximum 60 categories.')
                _require(len(set(labels))==len(labels),'Categories must be unique.')
                x=np.arange(len(labels));bottom=np.zeros(len(labels))
                if kind=='stacked_bar':_require(all(np.all(y>=0) for y in a),'Stacked composition requires nonnegative values.')
                for i,(name,y) in enumerate(zip(req.columns,a)):
                    if kind=='grouped_bar':ax.bar(x+(i-(len(a)-1)/2)*.8/len(a),y,.8/len(a),label=name)
                    else:ax.bar(x,y,bottom=bottom,label=name);bottom+=y
                ax.set_xticks(x,labels,rotation=35,ha='right');ylabel='Value (compatible units)'
                save_rows([req.x,*req.columns],labels,*a)
            ax.legend(frameon=False)
        elif kind in {'horizontal_bar','lollipop','pie','rank_change','tornado'}:
            names=[req.y]+([req.z] if kind=='rank_change' else [req.low,req.high] if kind=='tornado' else [])
            a,c=rows(names,[req.x]);labels=c[0];y=a[0]
            _require(len(labels)<=50 and len(set(labels))==len(labels),'Use at most 50 unique categories.')
            pos=np.arange(len(labels))
            if kind=='horizontal_bar':ax.barh(pos,y,color=color);ax.set_yticks(pos,labels);xlabel=req.y;ylabel=req.x
            elif kind=='lollipop':ax.hlines(pos,0,y,color=color);ax.scatter(y,pos,color=color);ax.set_yticks(pos,labels);xlabel=req.y;ylabel=req.x
            elif kind=='pie':
                _require(np.all(y>=0) and y.sum()>0 and len(y)<=12,'Pie requires 1–12 nonnegative categories and positive total.')
                ax.pie(y,labels=labels,autopct='%1.1f%%',colors=palette);xlabel=ylabel=''
            elif kind=='rank_change':
                z=a[1];r1=average_rank(y);r2=average_rank(z)
                for i,label in enumerate(labels):ax.plot([0,1],[r1[i],r2[i]],marker='o',label=label,color=palette[i%8])
                ax.set_xticks([0,1],[req.y,req.z]);ax.invert_yaxis();ax.legend(fontsize='small',frameon=False,bbox_to_anchor=(1,1));xlabel='Metric';ylabel='Rank (1 = highest)'
                save_rows([req.x,'rank_'+req.y,'rank_'+req.z],labels,r1,r2)
            else:
                low,high=a[1:];order=np.argsort(-np.abs(high-low),kind='stable')
                ax.barh(pos,low[order]-y[order],color=palette[0],height=.35,label='Low setting')
                ax.barh(pos+.35,high[order]-y[order],color=palette[1],height=.35,label='High setting')
                ax.set_yticks(pos+.175,labels[order]);ax.invert_yaxis();ax.axvline(0,color='#444444',linewidth=.8);ax.legend(frameon=False)
                xlabel='Response change from baseline';ylabel=req.x
                save_rows([req.x,'baseline','low_response','high_response','span'],labels[order],y[order],low[order],high[order],np.abs(high-low)[order])
            if not derived:save_rows([req.x,req.y],labels,y)
        elif kind in {'errorbar','uncertainty_band'}:
            a,_=rows([req.x,req.y,req.low,req.high]);x,y,lo,hi=a
            _require(np.all((lo<=y)&(y<=hi)),'Every interval must contain its central estimate.')
            order=np.argsort(x,kind='stable');x,y,lo,hi=[v[order] for v in a]
            if kind=='errorbar':ax.errorbar(x,y,yerr=[y-lo,hi-y],fmt='o',capsize=3,color=color)
            else:
                _require(len(x)>=2 and np.all(np.diff(x)>0),'Interval bands require distinct increasing x.')
                ax.fill_between(x,lo,hi,color=color,alpha=.2,label='Supplied interval');ax.plot(x,y,color=color,label='Central estimate');ax.legend(frameon=False)
            save_rows([req.x,req.y,req.low,req.high],x,y,lo,hi)
        elif kind in {'stem','step','residual_fit','hexbin','bubble','scale_location','pareto','scatter_3d'}:
            if kind in {'bubble','scatter_3d'}:a,_=rows([req.x,req.y,req.z]);x,y,z=a
            else:x,y=xy()
            if kind=='stem':ax.stem(x,y,linefmt=color,markerfmt='o',basefmt='k-')
            elif kind=='step':
                x,y=regular_series(x,y);ax.step(x,y,where='post',color=color)
            elif kind=='hexbin':
                h=ax.hexbin(x,y,gridsize=40,mincnt=1,cmap=cmap);fig.colorbar(h,ax=ax,label='Observation count')
                offsets=h.get_offsets();save_rows(['hex_center_x','hex_center_y','count'],offsets[:,0],offsets[:,1],h.get_array())
            elif kind=='bubble':
                _require(np.all(z>=0) and z.max()>0,'Bubble area requires nonnegative sizes and positive maximum.')
                size=280*z/z.max();ax.scatter(x,y,s=size,alpha=.6,edgecolors=color,facecolors='none')
                for v in [z.max()/4,z.max()/2,z.max()]:ax.scatter([],[],s=280*v/z.max(),facecolors='none',edgecolors=color,label=f'{v:.4g}')
                ax.legend(title=req.z,frameon=False);save_rows([req.x,req.y,req.z],x,y,z)
            elif kind in {'residual_fit','scale_location'}:
                fitted,residual,slope,intercept=linear_fit(x,y);meta.update(slope=slope,intercept=intercept)
                if kind=='residual_fit':ax.scatter(fitted,residual,s=9,alpha=.7);ax.axhline(0,color='#666666',linestyle='--');ylabel='Residual'
                else:
                    std=float(np.sqrt(np.sum(residual**2)/(len(x)-2)));_require(std>0,'Scale-location diagnostic requires nonzero residual variance.')
                    leverage=1/len(x)+(x-x.mean())**2/np.sum((x-x.mean())**2)
                    _require(np.all(leverage<1),'Standardized residuals undefined at unit leverage.')
                    scaled=np.sqrt(np.abs(residual/(std*np.sqrt(1-leverage))));ax.scatter(fitted,scaled,s=9,alpha=.7);ylabel='√|Standardized residual|'
                xlabel='Fitted '+req.y;save_rows([req.x,req.y,'fitted','residual'],x,y,fitted,residual)
            elif kind=='pareto':
                mask=pareto_mask(x,y,req.maximize_x,req.maximize_y);ax.scatter(x[~mask],y[~mask],s=17,color='#9299a0',label='Dominated')
                ax.scatter(x[mask],y[mask],s=28,color=palette[1],label='Nondominated')
                order=np.argsort(x[mask]);ax.plot(x[mask][order],y[mask][order],color=palette[1],linewidth=1,linestyle='--');ax.legend(frameon=False)
                xlabel+= ' (maximize)' if req.maximize_x else ' (minimize)';ylabel+=' (maximize)' if req.maximize_y else ' (minimize)'
                save_rows([req.x,req.y,'nondominated'],x,y,mask.astype(int))
            else:ax.scatter(x,y,z,c=z,cmap=cmap,s=12);ax.set_zlabel(req.z);save_rows([req.x,req.y,req.z],x,y,z)
            if not derived:save_rows([req.x,req.y],x,y)
        elif kind in {'violin','strip','overlay_hist'}:
            keys,groups=grouped();pos=np.arange(1,len(keys)+1)
            if kind=='violin':
                _require(all(len(v)>=2 and np.ptp(v)>0 for v in groups),'Each violin group needs at least two varying values.')
                parts=ax.violinplot(groups,positions=pos,showmedians=True)
                for i,b in enumerate(parts['bodies']):b.set_facecolor(palette[i%8]);b.set_alpha(.5)
                ax.set_xticks(pos,keys,rotation=35,ha='right')
            elif kind=='strip':
                for i,g in enumerate(groups):ax.scatter(np.full(len(g),pos[i]),g,s=8,alpha=.5,color=palette[i%8])
                ax.set_xticks(pos,keys,rotation=35,ha='right')
            else:
                allvalues=np.concatenate(groups);edges=np.histogram_bin_edges(allvalues,bins=30)
                for i,(name,g) in enumerate(zip(keys,groups)):ax.hist(g,bins=edges,histtype='step',density=True,label=name,color=palette[i%8],linewidth=1.5)
                ax.legend(frameon=False);xlabel=req.y;ylabel='Probability density'
                for name,g in zip(keys,groups):
                    values,_=np.histogram(g,bins=edges,density=True)
                    if not derived:derived.append(['group','lower','upper','density'])
                    derived.extend([[name,float(a),float(b),float(v)] for a,b,v in zip(edges[:-1],edges[1:],values)])
            if kind!='overlay_hist':xlabel=req.group;ylabel=req.y;save_rows([req.group,req.y],np.repeat(keys,[len(g) for g in groups]),np.concatenate(groups))
        elif kind in {'kde','rug','normal_fit'}:
            a,_=rows([req.y]);y=a[0];xlabel=req.y
            if kind=='rug':
                ax.plot(y,np.zeros_like(y),'|',color=color,alpha=.6);ax.set_yticks([]);ylabel='';save_rows([req.y],y)
            else:
                _require(len(y)>=2 and np.ptp(y)>0,'Density requires a varying sample.')
                std=float(y.std(ddof=1));band=1.06*std*len(y)**(-.2)
                _require(band>0,'Density bandwidth is undefined.')
                x=np.linspace(y.min()-3*band,y.max()+3*band,256)
                if kind=='kde':
                    # Chunked direct Gaussian KDE, not a sample of the input.
                    density=np.zeros(len(x))
                    for start in range(0,len(y),2048):
                        d=(x[:,None]-y[start:start+2048])/band;density+=np.exp(-.5*d*d).sum(axis=1)
                    density/=len(y)*band*np.sqrt(2*np.pi);meta['bandwidth']=band
                else:
                    x=np.linspace(y.min()-std,y.max()+std,256);density=np.exp(-.5*((x-y.mean())/std)**2)/(std*np.sqrt(2*np.pi))
                    ax.hist(y,bins=30,density=True,color=color,alpha=.3,label='Observed');ax.legend(frameon=False)
                ax.plot(x,density,color=color,linewidth=1.5);ylabel='Probability density';save_rows([req.y,'density'],x,density)
        elif kind in {'correlation_matrix','scatter_matrix','parallel_coordinates','radar'}:
            _require(2<=len(req.columns)<=8,'Choose two to eight numeric metrics.')
            a,c=rows(req.columns,[req.x] if kind=='radar' else []);matrix=np.column_stack(a)
            _require(matrix.shape[0]>=2,'At least two observations are required.')
            if kind=='correlation_matrix':
                _require(np.all(np.ptp(matrix,axis=0)>0),'Constant columns have undefined Pearson correlation.')
                r=np.corrcoef(matrix,rowvar=False);im=ax.imshow(r,vmin=-1,vmax=1,cmap='RdBu_r');fig.colorbar(im,ax=ax,label='Pearson r')
                ax.set_xticks(range(len(a)),req.columns,rotation=45,ha='right');ax.set_yticks(range(len(a)),req.columns)
                for i in range(len(a)):
                    for j in range(len(a)):ax.text(j,i,f'{r[i,j]:.2f}',ha='center',va='center',fontsize=max(6,req.font_size-2),color='white' if abs(r[i,j])>.65 else '#222222')
                derived.extend([['metric',*req.columns],*[[name,*map(float,v)] for name,v in zip(req.columns,r)]])
                xlabel=ylabel=''
            elif kind=='scatter_matrix':
                _require(len(a)<=5,'Scatter matrix supports two to five columns.')
                fig.delaxes(ax);axes=fig.subplots(len(a),len(a),squeeze=False)
                for i in range(len(a)):
                    for j in range(len(a)):
                        aa=axes[i,j]
                        if i==j:aa.hist(matrix[:,i],bins=20,color=color)
                        else:aa.scatter(matrix[:,j],matrix[:,i],s=3,alpha=.25,color=color)
                        if i==len(a)-1:aa.set_xlabel(req.columns[j],fontsize=7)
                        else:aa.set_xticklabels([])
                        if j==0:aa.set_ylabel(req.columns[i],fontsize=7)
                        else:aa.set_yticklabels([])
                ax=None;save_rows(req.columns,*a)
            else:
                v=normalized(matrix)
                if kind=='parallel_coordinates':
                    _require(len(v)<=2000,'Parallel coordinates supports up to 2,000 complete observations.')
                    # The final normalized metric supplies a continuous legend instead of arbitrary repeating colors.
                    for i,line in enumerate(v):ax.plot(range(len(a)),line,color=colormaps['viridis' if req.palette!='mono' else 'Greys'](line[-1]),alpha=.35 if len(v)>20 else .85,linewidth=req.line_width)
                    from matplotlib.cm import ScalarMappable
                    from matplotlib.colors import Normalize
                    fig.colorbar(ScalarMappable(norm=Normalize(0,1),cmap=colormaps['viridis' if req.palette!='mono' else 'Greys'].resampled(128)),ax=ax,label=req.columns[-1]+' (normalized)',shrink=.85)
                    ax.set_xticks(range(len(a)),req.columns,rotation=25,ha='right');ax.set_ylim(0,1);xlabel='Metric';ylabel='Normalized value'
                    save_rows(req.columns,*v.T)
                else:
                    labels=c[0];_require(len(labels)<=12 and len(set(labels))==len(labels),'Radar requires at most 12 unique scenarios.')
                    angle=np.linspace(0,2*np.pi,len(a),endpoint=False);closed=np.r_[angle,angle[0]]
                    for i,row in enumerate(v):ax.plot(closed,np.r_[row,row[0]],label=labels[i],color=palette[i%8])
                    ax.set_xticks(angle,req.columns);ax.set_ylim(0,1);ax.legend(frameon=False,bbox_to_anchor=(1.15,1));xlabel=ylabel=''
                    save_rows([req.x,*req.columns],labels,*v.T)
        elif kind in {'sobol','morris'}:
            _require(1<=len(req.columns)<=12,'Choose one to twelve factors.')
            if kind=='sobol':
                a,_=rows([req.x,req.y,*req.columns]);_require(count==len(table.rows),'Sobol design rows cannot be missing; supply the complete aligned design.');first,total=sobol_indices(a[0],a[1],a[2:])
                pos=np.arange(len(first));ax.bar(pos-.18,first,.36,label='First order');ax.bar(pos+.18,total,.36,label='Total order')
                ax.axhline(0,color='#444444',linewidth=.7);ax.set_xticks(pos,req.columns,rotation=30,ha='right');ax.legend(frameon=False)
                xlabel='Factor';ylabel='Sobol index';save_rows(['factor','first_order','total_order'],req.columns,first,total)
            else:
                a,c=rows([req.y,*req.columns],[req.x]);_require(count==len(table.rows),'Morris design rows cannot be missing.');mu,sigma=morris_effects(c[0],a[0],np.column_stack(a[1:]))
                ax.scatter(mu,sigma,color=color)
                for name,x,y in zip(req.columns,mu,sigma):ax.annotate(name,(x,y),xytext=(3,3),textcoords='offset points',fontsize=8)
                xlabel='μ* (mean absolute effect)';ylabel='σ (effect SD)';save_rows(['factor','mu_star','sigma'],req.columns,mu,sigma)
        elif kind=='response_surface':
            x,y,z=response_grid(table,req.x,req.y,req.z);xx,yy=np.meshgrid(x,y)
            valid=np.isfinite(z);masked=np.ma.masked_invalid(z)
            cm=colormaps[cmap].copy();cm.set_bad('#e5e5e5')
            style=req.response_style
            if style=='surface':
                _require(np.any(valid[:-1,:-1]&valid[:-1,1:]&valid[1:,:-1]&valid[1:,1:]),
                         'Surface requires at least one complete adjacent grid cell.')
                # Only draw quads whose four actual corner evaluations exist.
                from mpl_toolkits.mplot3d.art3d import Poly3DCollection
                from matplotlib.colors import Normalize
                full=valid[:-1,:-1]&valid[:-1,1:]&valid[1:,:-1]&valid[1:,1:]
                faces=[];colors=[]
                for i,j in zip(*np.where(full)):
                    indexes=((i,j),(i,j+1),(i+1,j+1),(i+1,j))
                    faces.append([(xx[a,b],yy[a,b],z[a,b]) for a,b in indexes])
                    colors.append(np.mean([z[a,b] for a,b in indexes]))
                surf=Poly3DCollection(faces,cmap=cm,norm=Normalize(float(np.nanmin(z)),float(np.nanmax(z))),edgecolor='#cccccc',linewidth=.25)
                surf.set_array(np.asarray(colors));ax.add_collection3d(surf);ax.auto_scale_xyz(xx[valid],yy[valid],z[valid]);ax.set_zlabel(req.z)
            elif style=='heatmap':
                surf=ax.pcolormesh(cell_edges(x),cell_edges(y),masked,cmap=cm,shading='flat')
                if req.show_values and z.size<=144:
                    lo,hi=np.nanmin(z),np.nanmax(z)
                    for i,j in np.ndindex(z.shape):
                        text=f'{z[i,j]:.3g}' if valid[i,j] else 'N/A'
                        ink='white' if valid[i,j] and hi>lo and (z[i,j]-lo)/(hi-lo)<.38 else '#222222'
                        ax.text(x[j],y[i],text,ha='center',va='center',fontsize=max(6,req.font_size-2),color=ink)
            else:
                _require(np.nanmax(z)>np.nanmin(z),'Contours require varying responses.')
                _require(np.any(valid[:-1,:-1]&valid[:-1,1:]&valid[1:,:-1]&valid[1:,1:]),'Contours require a complete adjacent grid cell.')
                levels=np.linspace(np.nanmin(z),np.nanmax(z),req.contour_levels)
                ax.set_facecolor('#e5e5e5')
                if style=='filled':
                    surf=ax.contourf(xx,yy,masked,levels=levels,cmap=cm,corner_mask=False)
                    cs=ax.contour(xx,yy,masked,levels=levels[1:-1],colors='#555555',linewidths=.45,corner_mask=False)
                else:
                    surf=cs=ax.contour(xx,yy,masked,levels=levels,cmap=cm,linewidths=req.line_width,corner_mask=False)
                if req.show_values:ax.clabel(cs,inline=True,fontsize=max(6,req.font_size-2),fmt='%.3g')
            fig.colorbar(surf,ax=ax,shrink=.8,label=req.z)
            if req.show_points:
                if style=='surface':ax.scatter(xx[valid],yy[valid],z[valid],s=9,color='#333333',depthshade=False)
                else:ax.scatter(xx[valid],yy[valid],s=9,facecolors='white',edgecolors='#333333',linewidths=.5)
            if req.optimum!='none':
                idx=np.unravel_index(np.nanargmin(z) if req.optimum=='min' else np.nanargmax(z),z.shape)
                point=[float(xx[idx]),float(yy[idx]),float(z[idx])]
                if style=='surface':ax.scatter(*point,s=65,marker='*',color='#e85a35',edgecolors='black')
                else:ax.scatter(*point[:2],s=80,marker='*',color='#e85a35',edgecolors='black',label='Observed '+req.optimum);ax.legend(frameon=False,loc=req.legend_position)
                meta['observed_optimum']=point
            derived.extend(numeric_rows([req.x,req.y,req.z],xx.ravel(),yy.ravel(),z.ravel()))
            meta.update(used_count=int(valid.sum()),grid_positions=int(z.size),missing_positions=int((~valid).sum()),response_style=style,
                        interpolation='none' if style=='heatmap' else 'visual interpolation within complete evaluated cells only')
        elif kind in {'time_trend','rolling_mean','seasonal_cycle','seasonal_anomaly','autocorrelation','lag_scatter','seasonal_heatmap'}:
            x,y=xy();_require(kind=='time_trend' or count==len(table.rows),'Regular time series must contain every observation; explicitly handle missing samples before analysis.');x,y=regular_series(x,y,kind!='time_trend')
            if kind=='time_trend':
                fitted,residual,slope,intercept=linear_fit(x,y);ax.plot(x,y,label='Observed');ax.plot(x,fitted,'--',label='Linear trend');ax.legend(frameon=False);meta.update(slope=slope,intercept=intercept);save_rows([req.x,req.y,'trend'],x,y,fitted)
            else:
                _require(float(parameter).is_integer(),'Window, period or lag must be an integer.')
                n=int(parameter);_require(n<len(y),'Window, period or lag must be shorter than the series.')
                if kind=='rolling_mean':
                    mean=np.convolve(y,np.ones(n)/n,mode='valid');ax.plot(x,y,alpha=.4,label='Observed');ax.plot(x[n-1:],mean,label='Trailing mean');ax.legend(frameon=False);save_rows([req.x,'trailing_mean'],x[n-1:],mean)
                elif kind=='autocorrelation':
                    centered=y-y.mean();den=float(centered@centered);_require(den>0,'Constant series has undefined autocorrelation.')
                    lag=np.arange(n+1);acf=np.array([float(centered[k:]@centered[:len(y)-k]/den) for k in lag])
                    ax.vlines(lag,0,acf,color=color);ax.scatter(lag,acf,s=13);ax.axhline(0,color='#777777',linewidth=.7);xlabel='Lag (samples)';ylabel='Autocorrelation';save_rows(['lag','acf'],lag,acf)
                elif kind=='lag_scatter':
                    ax.scatter(y[:-n],y[n:],s=12,alpha=.65);xlabel=req.y+' (t − lag)';ylabel=req.y+' (t)';save_rows(['lagged','current'],y[:-n],y[n:])
                else:
                    _require(len(y)>=2*n,'Seasonal summaries require at least two complete cycles.')
                    phase=np.arange(len(y))%n;means=np.array([y[phase==i].mean() for i in range(n)])
                    if kind=='seasonal_cycle':
                        ax.plot(np.arange(1,n+1),means,marker='o',markersize=3);xlabel='Phase (samples)';save_rows(['phase','mean'],np.arange(1,n+1),means)
                    elif kind=='seasonal_anomaly':
                        anomaly=y-means[phase];ax.plot(x,anomaly);ax.axhline(0,color='#777777',linewidth=.7);ylabel='Seasonal anomaly';save_rows([req.x,'anomaly'],x,anomaly)
                    else:
                        cycles=int(math.ceil(len(y)/n));grid=np.full(cycles*n,np.nan);grid[:len(y)]=y;grid=grid.reshape(cycles,n)
                        im=ax.imshow(grid,aspect='auto',origin='lower',interpolation='nearest',cmap=cmap,extent=(.5,n+.5,.5,cycles+.5));fig.colorbar(im,ax=ax,label=req.y);xlabel='Phase';ylabel='Cycle';save_rows(['cycle','phase',req.y],np.arange(len(y))//n+1,phase+1,y)
        elif source=='raster':
            g=grids[0];z=g.values;unit=g.unit or 'value (unit unspecified)'
            def map_axes(a,grid):
                a.set_aspect('equal');a.set_xlabel('Easting' if grid.crs.is_projected else 'Longitude / x');a.set_ylabel('Northing' if grid.crs.is_projected else 'Latitude / y')
                a.ticklabel_format(style='plain',useOffset=False);a.tick_params(labelsize=max(6,req.font_size-2));a.xaxis.set_major_locator(MaxNLocator(4));a.yaxis.set_major_locator(MaxNLocator(4))
                a.annotate('Grid N',xy=(.94,.92),xytext=(.94,.79),xycoords='axes fraction',textcoords='axes fraction',arrowprops={'arrowstyle':'-|>','color':'#333333'},ha='center',fontsize=7)
                if grid.is_meter:
                    xmin,xmax,ymin,ymax=grid.extent;target=(xmax-xmin)*.22;power=10**math.floor(math.log10(target));length=max(v*power for v in (.1,.2,.5,1,2,5,10) if v*power<=target)
                    ax0=xmin+(xmax-xmin)*.06;ay0=ymin+(ymax-ymin)*.06;a.plot([ax0,ax0+length],[ay0,ay0],color='black',linewidth=3);a.plot([ax0,ax0+length],[ay0,ay0],color='white',linewidth=1)
                    a.text(ax0+length/2,ay0+(ymax-ymin)*.025,f'{length/1000:g} km' if length>=1000 else f'{length:g} m',ha='center',fontsize=7,bbox={'facecolor':'white','alpha':.8,'edgecolor':'none','pad':1})
            def show(a,values,grid,cm=cmap,vmin=None,vmax=None,label=None):
                if grid_sink is not None:
                    from .studio_inference import geotiff_product
                    units={'raster_slope':'degree','raster_hillshade':'unitless','raster_exceedance':'unitless'}
                    grid_sink.append(geotiff_product(grid,values,units.get(kind,grid.unit),kind,[{'sha256':v.sha256,'band':v.band} for v in grids]))
                cm=colormaps[cm].copy() if isinstance(cm,str) else cm.copy();cm.set_bad('#e9e9e9')
                im=a.imshow(values,extent=grid.extent,origin='upper',interpolation='nearest',cmap=cm,vmin=vmin,vmax=vmax);map_axes(a,grid)
                meta.update(display_min=float(im.norm.vmin),display_max=float(im.norm.vmax),nodata_display='#e9e9e9')
                if label:fig.colorbar(im,ax=a,label=label,shrink=.85)
                return im
            if kind=='raster_profile':
                _require(bool(req.csv),'Supply a path coordinate CSV in the grid CRS.')
                path=Table(req.csv);distance,values=raster_profiles(grids,path,req.x,req.y)
                if req.profile_style=='delta':
                    _require(len(grids)>=2,'Difference profile needs at least two rasters.')
                    values=values[1:]-values[0];names=[item.name+' − '+grids[0].name for item in grids[1:]]
                    ax.axhline(0,color='#777777',linewidth=.8)
                elif req.profile_style=='bands':
                    _require(len(grids)%3==0,'Select raster mean, lower, upper triples in that order.')
                    names=[item.name for item in grids]
                    for i in range(0,len(grids),3):
                        mean,low,high=values[i:i+3];mask=np.isfinite(mean)&np.isfinite(low)&np.isfinite(high)
                        _require(mask.any() and np.all((low[mask]<=mean[mask])&(mean[mask]<=high[mask])),'Invalid supplied raster bounds.')
                        ax.fill_between(distance,low,high,where=mask,color=palette[(i//3)%8],alpha=.2)
                        ax.plot(distance,mean,label=names[i],color=palette[(i//3)%8],linewidth=req.line_width)
                else:names=[item.name for item in grids]
                if req.profile_style!='bands':
                    for i,(name,v) in enumerate(zip(names,values)):ax.plot(distance,v,label=name,color=palette[i%8],linewidth=req.line_width,linestyle=['-','--','-.',':'][i%4])
                _require(np.isfinite(values).any(),'No common profile observations.')
                ax.legend(frameon=False,loc=req.legend_position);xlabel='Distance along supplied path (m)';ylabel=unit if req.profile_style!='delta' else 'Difference ('+unit+')'
                derived.extend(numeric_rows(['distance_m',*names],distance,*values));meta.update(input_count=len(distance),used_count=int(np.any(np.isfinite(values),axis=0).sum()),sampling='native pixel at each supplied projected path coordinate',profile_style=req.profile_style)
            elif kind=='hypsometric':
                _require(g.is_meter and g.unit in ('m','meter','metre'),'Hypsometry requires a projected metre grid and declared metre elevation.')
                values=np.sort(z[np.isfinite(z)]);_require(np.ptp(values)>0,'Hypsometry is undefined for a constant surface.')
                samples=np.linspace(values[0],values[-1],256);area=1-np.searchsorted(values,samples,side='left')/len(values);rel=(samples-values[0])/np.ptp(values)
                ax.plot(area,rel,color=color);ax.set_xlim(0,1);ax.set_ylim(0,1);xlabel='Relative area at or above elevation';ylabel='Relative elevation';meta['hypsometric_integral']=float((values.mean()-values[0])/np.ptp(values));save_rows(['relative_area','relative_elevation'],area,rel)
            elif kind=='raster_matrix':
                stack,common=aligned_grids(grids);lo=float(np.nanmin(stack));hi=float(np.nanmax(stack));fig.delaxes(ax)
                if req.map_common_mask:stack=np.where(common[None,:,:],stack,np.nan);lo=float(np.nanmin(stack));hi=float(np.nanmax(stack))
                mode=req.map_style
                if req.map_min is not None or req.map_max is not None:
                    _require(req.map_min is not None and req.map_max is not None and req.map_min<req.map_max,'Supply an increasing fixed display range.')
                    lo,hi=req.map_min,req.map_max
                if mode=='diverging':limit=max(abs(lo),abs(hi),1e-12);lo,hi=-limit,limit
                if lo==hi:lo-=.5;hi+=.5
                cols=req.map_columns or (2 if len(grids)<=4 else 3);axes=fig.subplots(math.ceil(len(grids)/cols),cols,squeeze=False,sharex=True,sharey=True);used=[]
                if mode=='categorical':
                    codes=np.unique(stack[np.isfinite(stack)]);_require(len(codes)<=24,'Categorical matrix supports at most 24 codes.')
                    colors=[to_hex(colormaps['tab20'](i)) for i in range(min(20,len(codes)))]+[to_hex(colormaps['tab20b'](i)) for i in range(max(0,len(codes)-20))]
                    cm=ListedColormap(colors);norm=BoundaryNorm(np.arange(len(codes)+1)-.5,len(codes))
                elif req.class_breaks:
                    levels=np.asarray(req.class_breaks);_require(np.all(np.diff(levels)>0),'Class breaks must increase.')
                    _require(levels[0]<=np.nanmin(stack) and levels[-1]>=np.nanmax(stack),'Class breaks must span all displayed values.')
                    cm=colormaps['RdBu_r' if mode=='diverging' else cmap].resampled(len(levels)-1);norm=BoundaryNorm(levels,len(levels)-1)
                    lo,hi=float(levels[0]),float(levels[-1])
                else:
                    from matplotlib.colors import Normalize
                    cm=colormaps['RdBu_r' if mode=='diverging' else cmap];norm=Normalize(lo,hi,clip=False)
                for i,a in enumerate(axes.flat):
                    if i>=len(grids):a.set_visible(False);continue
                    values=stack[i]
                    if mode=='categorical':
                        indexed=np.full(values.shape,np.nan)
                        for j,code in enumerate(codes):indexed[values==code]=j
                        values=indexed
                    im=a.imshow(values,extent=grids[i].extent,origin='upper',interpolation='nearest',cmap=cm,norm=norm)
                    map_axes(a,grids[i]);a.set_title(f'({chr(97+i)}) '+grids[i].name[:65],loc='left',fontsize=req.font_size);used.append(a)
                if mode=='categorical':
                    cb=fig.colorbar(im,ax=used,shrink=.8,ticks=np.arange(len(codes)),label='Class code');cb.ax.set_yticklabels([f'{c:g}' for c in codes])
                    meta['class_codes']=codes.tolist()
                else:
                    actual_lo,actual_hi=float(np.nanmin(stack)),float(np.nanmax(stack))
                    extension='both' if actual_lo<lo and actual_hi>hi else 'min' if actual_lo<lo else 'max' if actual_hi>hi else 'neither'
                    fig.colorbar(im,ax=used,label=unit,shrink=.8,extend=extension)
                ax=None;meta.update(common_cells=int(common.sum()),display_min=lo,display_max=hi,map_style=mode,map_columns=cols,common_mask=req.map_common_mask,extent=list(grids[0].extent))
            elif kind in {'terrain_surface','terrain_wireframe','raster_contours','raster_hillshade','raster_slope'}:
                _require(g.is_meter and g.unit in ('m','meter','metre'),'Terrain operations require a projected metre grid and declared metre elevations.')
                x,y=g.axes
                _require(min(z.shape)>=3,'Terrain derivative and surface need at least three rows and columns.')
                if kind in {'terrain_surface','terrain_wireframe'}:
                    step=max(1,math.ceil(max(z.shape)/120));xx,yy=np.meshgrid(x[::step]-x[0],y[::step]-y[-1]);zz=z[::step,::step]
                    if kind=='terrain_surface':surf=ax.plot_surface(xx,yy,zz,cmap=cmap,linewidth=0);fig.colorbar(surf,ax=ax,label='Elevation (m)',shrink=.6)
                    else:ax.plot_wireframe(xx,yy,zz,rstride=2,cstride=2,color=color,linewidth=.4)
                    xlabel='Grid easting offset (m)';ylabel='Grid northing offset (m)';ax.set_zlabel('Elevation (m)');meta['render_stride']=step
                elif kind=='raster_contours':
                    _require(float(parameter).is_integer() and np.nanmax(z)>np.nanmin(z),'Contours require integer level count and varying elevation.')
                    cs=ax.contour(x,y,z,levels=int(parameter),cmap=cmap,linewidths=.7);ax.clabel(cs,inline=True,fontsize=7);fig.colorbar(cs,ax=ax,label='Elevation (m)');map_axes(ax,g);xlabel=ylabel=''
                elif kind=='raster_hillshade':
                    shade=LightSource(azdeg=315,altdeg=45).hillshade(np.ma.masked_invalid(z),dx=g.transform.a,dy=-g.transform.e);show(ax,shade,g,'gray',0,1,'Illumination');xlabel=ylabel=''
                else:
                    gy,gx=np.gradient(z,-g.transform.e,g.transform.a);slope=np.degrees(np.arctan(np.hypot(gx,gy)));slope[~np.isfinite(z)]=np.nan
                    show(ax,slope,g,label='Slope (degrees)');xlabel=ylabel='';meta['used_count']=int(np.isfinite(slope).sum())
            elif kind=='raster_classes':
                codes=np.unique(z[np.isfinite(z)]);_require(len(codes)<=24,'Categorical map supports at most 24 numeric codes.')
                indexed=np.full(z.shape,np.nan);counts=[]
                for i,code in enumerate(codes):mask=z==code;indexed[mask]=i;counts.append(int(mask.sum()))
                class_colors=[to_hex(colormaps['tab20'](i)) for i in range(min(20,len(codes)))]+[to_hex(colormaps['tab20b'](i)) for i in range(max(0,len(codes)-20))]
                if req.palette=='mono':class_colors=[to_hex(colormaps['Greys'](.15+.8*i/max(1,len(codes)-1))) for i in range(len(codes))]
                im=ax.imshow(indexed,extent=g.extent,origin='upper',interpolation='nearest',cmap=ListedColormap(class_colors),norm=BoundaryNorm(np.arange(len(codes)+1)-.5,len(codes)))
                map_axes(ax,g);ax.legend(handles=[Patch(color=class_colors[i],label=f'{code:g}') for i,code in enumerate(codes)],frameon=False,bbox_to_anchor=(1,1),title='Class');xlabel=ylabel='';save_rows(['class','cell_count'],codes,counts)
            elif kind=='raster_continuous':show(ax,z,g,label=unit);xlabel=ylabel=''
            else:
                if kind in {'raster_difference','raster_significant_change'}:_require(len(grids)==MIN_RASTERS[kind],'Select exactly the required input rasters in order.')
                stack,common=aligned_grids(grids);out=np.full(z.shape,np.nan);valid=stack[:,common]
                if kind=='raster_difference':
                    out[common]=valid[1]-valid[0];lim=max(float(np.nanmax(np.abs(out))),1e-12);show(ax,out,g,'RdBu_r',-lim,lim,'Candidate − baseline ('+unit+')')
                elif kind=='raster_uncertainty':
                    out[common]=valid.std(axis=0,ddof=1);show(ax,out,g,label='Ensemble sample SD ('+unit+')')
                elif kind=='raster_exceedance':
                    out[common]=(valid>parameter).mean(axis=0);show(ax,out,g,vmin=0,vmax=1,label='Fraction exceeding threshold');meta['threshold']=parameter
                else:
                    _require(np.all(valid[2]>=0),'Difference standard deviation must be nonnegative.')
                    delta=valid[1]-valid[0];sd=valid[2];out[common]=np.where(delta>parameter*sd,1,np.where(delta<-parameter*sd,-1,0))
                    ax.imshow(out,extent=g.extent,origin='upper',interpolation='nearest',cmap=ListedColormap(['#3264a0','#eeeeee','#b34037']),norm=BoundaryNorm([-1.5,-.5,.5,1.5],3));map_axes(ax,g)
                    ax.legend(handles=[Patch(color=c,label=l) for c,l in zip(['#3264a0','#eeeeee','#b34037'],['Decrease','Within threshold','Increase'])],frameon=False,loc='upper left',fontsize=7)
                    meta['critical_multiplier']=parameter
                finite=out[np.isfinite(out)];meta.update(used_count=int(finite.size),minimum=float(finite.min()),maximum=float(finite.max()),mean=float(finite.mean()))
                xlabel=ylabel=''
            if ax is not None and kind not in {'hypsometric','terrain_surface','terrain_wireframe','raster_profile'}:xlabel=ylabel=''
        else:raise FigureInputError('Unimplemented figure recipe.')
        if ax is not None:
            if source!='raster' or kind in {'hypsometric','terrain_surface','terrain_wireframe','raster_profile'}:
                ax.set_xlabel(req.x_label or xlabel);ax.set_ylabel(req.y_label or ylabel)
                if kind not in {'pie','radar'}:ax.grid(req.grid,alpha=.18)
            if kind not in {'pie','radar','correlation_matrix'} and source=='table' and not is3d:
                if req.x_label:ax.set_xlabel(req.x_label)
                if req.y_label:ax.set_ylabel(req.y_label)
        if req.legend_position!='best':
            for axes in fig.axes:
                legend=axes.get_legend()
                if legend is not None and axes.name!='polar':legend.set_loc(req.legend_position)
        fig.suptitle(publication_title(panel_label+(req.title or title),req.width_mm if container is None else max(40,container.bbox.width/container.get_figure(root=True).dpi*25.4),req.font_size+2),fontsize=req.font_size+2,fontweight='medium')
        if table and not derived:meta['derived_note']='The plot uses the selected complete observations; original CSV is retained in the request.'
        if table and req.x_label:meta['x_label']=req.x_label
        if table and req.y_label:meta['y_label']=req.y_label
        meta['omitted_count']=max(0,meta['input_count']-meta['used_count'])
        meta['plot_table_rows']=max(0,len(derived)-1)
        if container is not None:return b'',meta,derived
        fit_publication_text(fig)
        meta['layout']=layout_receipt(fig)
        meta['publication']={'width_mm':req.width_mm,'height_mm':req.height_mm,'export_dpi':req.dpi,'format':req.format,'font_size_pt':req.font_size,'line_width_pt':req.line_width,'palette':req.palette}
        buffer=io.BytesIO()
        dpi=req.dpi
        if req.format=='tiff':fig.savefig(buffer,format='tiff',dpi=dpi,pil_kwargs={'compression':'tiff_lzw'})
        else:fig.savefig(buffer,format=req.format,dpi=dpi)
        fig.clear()
    return buffer.getvalue(),meta,derived
