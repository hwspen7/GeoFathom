"""Result-aware spatial research plots using the shared publication renderer."""
import numpy as np
from .studio_publication import require,numeric_rows

def render_spatial_figure(kind,req,fig,ax,table,meta,palette,cmap,rows):
    if kind=='spatial_null_distribution':
        a,_=rows([req.x,req.y]);null,observed=a
        require(len(null)>=2 and np.all(observed==observed[0]),'One observed statistic and at least two null draws required.')
        counts,edges=np.histogram(null,bins=min(35,max(5,int(np.sqrt(len(null))))))
        ax.stairs(counts,edges,fill=True,alpha=.55,color=palette[0])
        ax.axvline(observed[0],color=palette[1],linestyle='--',label='Observed statistic')
        ax.set(xlabel='Statistic under random-label null',ylabel='Permutation count');ax.legend()
        meta['observed_statistic']=float(observed[0]);meta['permutations']=len(null)
        return numeric_rows([req.x,req.y],null,observed)
    if kind=='spatial_directional_lag':
        a,c=rows([req.x,req.y],[req.group]);distance,value=a;groups=c[0]
        require(np.all(distance>0) and len(np.unique(groups))<=12,'Positive lag distances and at most 12 directions required.')
        for i,g in enumerate(dict.fromkeys(groups)):
            ids=np.flatnonzero(groups==g);order=ids[np.argsort(distance[ids])]
            require(len(np.unique(distance[order]))==len(order),'Duplicate distance within direction.')
            ax.plot(distance[order],value[order],marker='o',markersize=3,label=g,color=palette[i%len(palette)])
        ax.set(xlabel=req.x,ylabel=req.y);ax.legend()
        return numeric_rows([req.x,req.y,req.group],distance,value,groups)
    if kind=='spatial_sample_design':
        a,_=rows([req.x,req.y,req.z]);x,y,w=a
        require(np.all(w>0),'Design weights must be positive.')
        sizes=14+56*w/w.max()
        ax.scatter(x,y,s=sizes,c=w,cmap=cmap,alpha=.8,edgecolors='none');ax.set_aspect('equal',adjustable='datalim')
        fig.colorbar(ax.collections[0],ax=ax,label=req.z);ax.set(xlabel=req.x,ylabel=req.y)
        meta['total_design_weight']=float(w.sum());meta['method_note']='Symbol size and color indicate supplied design weight; coordinates must share a projected metric CRS.'
        return numeric_rows([req.x,req.y,req.z],x,y,w)
    if kind=='spatial_oof_agreement':
        a,c=rows([req.x,req.y],[req.group]);actual,pred=a;group=c[0];keys=list(dict.fromkeys(group))
        require(len(keys)<=24,'At most 24 validation folds.')
        for i,g in enumerate(keys):
            sel=group==g;ax.scatter(actual[sel],pred[sel],s=12,alpha=.65,label=g,color=palette[i%len(palette)])
        lo=min(actual.min(),pred.min());hi=max(actual.max(),pred.max())
        if lo==hi:lo-=.5;hi+=.5
        ax.plot([lo,hi],[lo,hi],color='gray',linestyle='--',label='1:1');ax.set(xlim=(lo,hi),ylim=(lo,hi),xlabel=req.x,ylabel=req.y)
        ax.set_aspect('equal',adjustable='box');ax.legend(ncol=2 if len(keys)>4 else 1)
        residual=actual-pred;meta['rmse']=float(np.sqrt(np.mean(residual**2)));meta['mae']=float(np.mean(abs(residual)))
        return numeric_rows([req.x,req.y,req.group,'residual'],actual,pred,group,residual)
    a,c=rows([req.y,req.z],[req.x]);valid,total=a;labels=c[0]
    require(len(labels)<=50 and len(set(labels))==len(labels) and np.all(total>0) and np.all(valid>=0) and np.all(valid<=total*(1+1e-8)),'Up to 50 unique zones with valid area between zero and total area required.')
    ratio=np.minimum(valid/total,1);pos=np.arange(len(labels))
    ax.barh(pos,ratio,color=palette[0],label='Valid');ax.barh(pos,1-ratio,left=ratio,color='#bdbdbd',label='Not valid / outside')
    ax.set(yticks=pos,yticklabels=labels,xlim=(0,1),xlabel='Fraction of zone area',ylabel=req.x);ax.legend();ax.invert_yaxis()
    return numeric_rows([req.x,req.y,req.z,'valid_fraction'],labels,valid,total,ratio)
