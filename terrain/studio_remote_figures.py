"""Publication diagnostics using actual remote-sensing model evidence."""
import numpy as np
from .studio_publication import require,numeric_rows

def render_remote(kind,req,fig,ax,meta,palette,cmap,rows):
    if kind=='remote_selective_accuracy':
        a,_=rows([req.x,req.y,req.z]);x,y,n=a
        require(np.all((x>=0)&(x<=1)&(y>=0)&(y<=1)) and np.all(n>0) and np.all(n==np.floor(n)),'Selective accuracy requires coverage, accuracy and accepted cell counts.')
        order=np.argsort(x);x,y,n=x[order],y[order],n[order]
        ax.plot(x,y,color=palette[0]);ax.scatter(x,y,s=20+100*n/n.max(),color=palette[0])
        ax.set(xlim=(0,1),ylim=(0,1),xlabel='Independent reference coverage',ylabel='Accuracy among accepted cells')
        meta['threshold_points']=len(x)
        return numeric_rows([req.x,req.y,req.z],x,y,n)
    if kind=='remote_reliability':
        a,_=rows([req.x,req.y,req.z]);x,y,n=a
        require(np.all((x>=0)&(x<=1)&(y>=0)&(y<=1)) and np.all(n>0) and np.all(n==np.floor(n)),'Reliability requires probabilities and positive integer bin counts.')
        order=np.argsort(x);x,y,n=x[order],y[order],n[order]
        ax.plot([0,1],[0,1],'--',color='gray',label='Ideal')
        ax.plot(x,y,color=palette[0],linewidth=.8)
        ax.scatter(x,y,s=24+140*n/n.max(),color=palette[0],alpha=.8,label='Held-out bins')
        ax.set(xlim=(0,1),ylim=(0,1),xlabel='Mean predicted probability',ylabel='Observed positive fraction')
        ax.set_aspect('equal',adjustable='box');ax.legend(loc='upper left')
        meta['ece']=float(np.sum(n*abs(x-y))/n.sum());meta['validation_cells']=int(n.sum())
        return numeric_rows([req.x,req.y,req.z],x,y,n)
    if kind=='remote_roc':
        a,_=rows([req.x,req.y]);x,y=a
        require(len(x)>=2 and np.all((x>=0)&(x<=1)&(y>=0)&(y<=1)) and np.all(np.diff(x)>=0) and np.all(np.diff(y)>=0),'ROC coordinates must be ordered in [0,1].')
        require(np.allclose([x[0],y[0],x[-1],y[-1]],[0,0,1,1]),'ROC endpoints must be (0,0) and (1,1).')
        ax.plot(x,y,color=palette[0],label='Held-out ROC');ax.fill_between(x,0,y,alpha=.12,color=palette[0])
        ax.plot([0,1],[0,1],'--',color='gray',label='Chance')
        ax.set(xlim=(0,1),ylim=(0,1),xlabel='False positive rate',ylabel='True positive rate')
        ax.set_aspect('equal',adjustable='box');ax.legend(loc='lower right')
        # Plotted curve may be decimated; exact original AUC remains in analysis receipt.
        meta['plotted_curve_auc']=float(np.trapezoid(y,x))
        return numeric_rows([req.x,req.y],x,y)
    if kind=='remote_joint_posterior':
        a,_=rows([req.x,req.y,req.z]);x,y,z=a
        require(np.all(z>=0) and np.isclose(z.sum(),1,atol=1e-7),'Joint posterior masses must sum to one.')
        points,inv=np.unique(np.column_stack((x,y)),axis=0,return_inverse=True);mass=np.bincount(inv,weights=z)
        x,y=points.T;z=mass
        art=ax.scatter(x,y,s=15+160*z/z.max(),c=z,cmap=cmap,edgecolors='none')
        fig.colorbar(art,ax=ax,label='Posterior mass')
        ax.set(xlabel=req.x,ylabel=req.y)
        meta['posterior_mass']=float(z.sum());meta['unique_parameter_pairs']=len(z)
        return numeric_rows([req.x,req.y,req.z],x,y,z)
    if kind=='remote_posterior_marginal':
        a,_=rows([req.x,req.y]);x,y=a
        require(len(np.unique(x))==len(x) and np.all(y>=0) and np.isclose(y.sum(),1,atol=1e-7),'Marginal posterior needs unique hypotheses and unit total probability.')
        order=np.argsort(x);x,y=x[order],y[order]
        ax.vlines(x,0,y,color=palette[0],linewidth=1);ax.scatter(x,y,s=12,color=palette[0])
        mean=float(x@y);ax.axvline(mean,linestyle='--',color=palette[1],label='Posterior mean')
        ax.set(xlabel=req.x,ylabel='Posterior mass',ylim=(0,max(y)*1.12));ax.legend()
        meta['posterior_mean']=mean
        return numeric_rows([req.x,req.y],x,y)
    a,_=rows([req.x,req.y]);x,y=a
    require(len(x)>=2 and np.all(np.diff(x)>0) and np.all((x>=0)&(x<=1)) and np.all(np.diff(y)>=-1e-10),'Ordered quantiles and nondecreasing residuals required.')
    ax.axhline(0,color='gray',linestyle='--');ax.plot(x,y,color=palette[0],marker='o',markersize=3)
    ax.fill_between(x,0,y,where=y>=0,interpolate=True,alpha=.18,color=palette[0])
    ax.fill_between(x,0,y,where=y<0,interpolate=True,alpha=.18,color=palette[1])
    ax.set(xlim=(0,1),xlabel='Quantile',ylabel='Signed anchor difference')
    return numeric_rows([req.x,req.y],x,y)
