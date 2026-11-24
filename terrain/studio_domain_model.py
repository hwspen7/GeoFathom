"""Validated model diagnostics, multivariate statistics and optimization plots."""
import numpy as np
from .studio_data import FigureInputError, linear_fit, regular_series, normalized
from .studio_publication import numeric_rows
from .studio_domain_table import require,ratio,ranks,table_matrix

def binary_curve(truth,score):
    require(np.all(np.isin(truth,[0,1])) and np.all((score>=0)&(score<=1)),'Binary labels 0/1 and probability scores in [0,1] required.')
    p=int(truth.sum());n=len(truth)-p;require(p>0 and n>0,'Both binary classes must be present.')
    order=np.argsort(-score,kind='stable');y=truth[order];s=score[order]
    ends=np.r_[np.flatnonzero(s[:-1]!=s[1:]),len(s)-1]
    tp=np.r_[0,np.cumsum(y)[ends]];fp=np.r_[0,(ends+1)-np.cumsum(y)[ends]]
    return np.r_[np.inf,s[ends]],tp,fp,p,n

def pca(matrix):
    require(len(matrix)>1,'PCA needs multiple observations.')
    sd=matrix.std(axis=0,ddof=1);require(np.all(sd>0),'Standardized PCA requires nonconstant columns.')
    scaled=(matrix-matrix.mean(axis=0))/sd
    _,singular,v=np.linalg.svd(scaled,full_matrices=False)
    require(len(singular)>=2,'At least two components required.')
    # Deterministic signs, chosen by largest absolute loading.
    for row in v:
        if row[np.argmax(np.abs(row))]<0:row*=-1
    eigen=singular**2/(len(matrix)-1);return scaled@v.T,eigen,v

def kmeans(matrix,k):
    require(2<=k<=min(len(matrix),12),'Invalid cluster count.')
    require(len(matrix)<=3000,'K-means supports up to 3,000 observations.')
    sd=matrix.std(axis=0);require(np.all(sd>0),'K-means requires varying columns.')
    z=(matrix-matrix.mean(axis=0))/sd
    require(len(np.unique(z,axis=0))>=k,'Fewer distinct observations than clusters.')
    # Farthest-first initialization, deterministic tie resolution.
    centers=[z[0]];minimum=np.full(len(z),np.inf)
    for _ in range(1,k):
        minimum=np.minimum(minimum,np.sum((z-centers[-1])**2,axis=1));centers.append(z[np.argmax(minimum)])
    c=np.array(centers);labels=np.zeros(len(z),dtype=int)
    for _ in range(100):
        distances=np.sum((z[:,None,:]-c[None,:,:])**2,axis=2)
        labels=distances.argmin(axis=1)
        new=c.copy()
        for j in range(k):
            if np.any(labels==j):new[j]=z[labels==j].mean(axis=0)
            else:new[j]=z[np.argmax(distances.min(axis=1))]
        if np.max(np.abs(new-c))<1e-10:break
        c=new
    distances=np.sum((z[:,None,:]-c[None,:,:])**2,axis=2);labels=distances.argmin(axis=1)
    require(len(np.unique(labels))==k,'Clustering produced empty groups.')
    return z,labels,float(distances.min(axis=1).sum())

def domination_counts(matrix):
    require(len(matrix)<=2500,'Exact multidimensional dominance is limited to 2,500 candidates.')
    out=np.zeros(len(matrix),dtype=int)
    for i,row in enumerate(matrix):out[i]=np.sum(np.all(matrix<=row,axis=1)&np.any(matrix<row,axis=1))
    return out

def render_model(kind,req,fig,ax,table,parameter,meta,palette,cmap,rows):
    derived=[]
    def save(headers,*arrays):
        derived.clear();derived.extend(numeric_rows(headers,*arrays))
    def xy():
        a,_=rows([req.x,req.y]);return a
    def xyz():
        a,_=rows([req.x,req.y,req.z]);return a
    def setxy(x,y):ax.set(xlabel=x,ylabel=y)
    def heat(mat,labels,label,cm=None,vmin=None,vmax=None):
        im=ax.imshow(mat,cmap=cm or cmap,vmin=vmin,vmax=vmax);fig.colorbar(im,ax=ax,label=label)
        ax.set_xticks(range(len(labels)),labels,rotation=35,ha='right');ax.set_yticks(range(len(labels)),labels)
    if kind in {'model_roc','model_pr','model_threshold','model_gain','model_lift','model_calibration'}:
        y,s=xy();threshold,tp,fp,p,n=binary_curve(y,s)
        recall=tp/p;fpr=fp/n;precision=ratio(tp,tp+fp);precision[0]=1
        if kind=='model_roc':
            auc=float(np.sum(np.diff(fpr)*(recall[:-1]+recall[1:])/2));ax.plot(fpr,recall,label=f'AUC = {auc:.3f}');ax.plot([0,1],[0,1],'--',color='gray');ax.legend(frameon=False);setxy('False positive rate','True positive rate');meta['auc']=auc;save(['fpr','tpr'],fpr,recall)
        elif kind=='model_pr':
            ap=float(np.sum(np.diff(recall)*precision[1:]));ax.step(recall,precision,where='pre',label=f'AP = {ap:.3f}');ax.axhline(p/(p+n),linestyle='--',color='gray');ax.legend(frameon=False);setxy('Recall','Precision');meta['average_precision']=ap;save(['recall','precision'],recall,precision)
        elif kind=='model_threshold':
            f1=ratio(2*tp,2*tp+fp+p-tp);ax.plot(threshold[1:],precision[1:],label='Precision');ax.plot(threshold[1:],recall[1:],label='Recall');ax.plot(threshold[1:],f1[1:],label='F1');ax.legend(frameon=False);setxy('Decision threshold','Score');save(['threshold','precision','recall','f1'],threshold[1:],precision[1:],recall[1:],f1[1:])
        elif kind=='model_calibration':
            bins=int(parameter);require(2<=bins<=50 and bins==parameter,'Choose 2–50 probability bins.')
            ids=np.minimum((s*bins).astype(int),bins-1);x=[];v=[];counts=[]
            for i in range(bins):
                m=ids==i
                if m.any():x.append(s[m].mean());v.append(y[m].mean());counts.append(m.sum())
            ax.plot([0,1],[0,1],'--',color='gray');ax.scatter(x,v,s=20+100*np.asarray(counts)/len(s));setxy('Mean predicted probability','Observed positive fraction');meta['brier_score']=float(np.mean((s-y)**2));save(['mean_probability','observed_fraction','count'],x,v,counts)
        else:
            fraction=(tp+fp)/(p+n)
            if kind=='model_gain':ax.plot(fraction,recall);ax.plot([0,1],[0,1],'--',color='gray');setxy('Selected fraction','Captured positive fraction');save(['selected_fraction','gain'],fraction,recall)
            else:
                lift=recall[1:]/fraction[1:];ax.plot(fraction[1:],lift);ax.axhline(1,color='gray',linestyle='--');setxy('Selected fraction','Cumulative lift');save(['selected_fraction','lift'],fraction[1:],lift)
    elif kind in {'model_confusion','model_class_metrics'}:
        observed=table.labels(req.x);predicted=table.labels(req.y);valid=(observed!='')&(predicted!='');observed,predicted=observed[valid],predicted[valid]
        labels=np.unique(np.r_[observed,predicted]);require(2<=len(labels)<=30,'Confusion analysis needs 2–30 class labels.')
        m=np.zeros((len(labels),len(labels)),dtype=int);np.add.at(m,(np.searchsorted(labels,observed),np.searchsorted(labels,predicted)),1)
        meta.update(used_count=int(valid.sum()),accuracy=float(m.trace()/m.sum()))
        if kind=='model_confusion':
            heat(m,labels,'Count');setxy('Predicted class','Observed class')
            if len(labels)<=10:
                for i,j in np.ndindex(m.shape):ax.text(j,i,str(m[i,j]),ha='center',va='center',fontsize=7,color='white' if m[i,j]>m.max()*.6 else 'black')
            derived.extend([['observed / predicted',*labels.tolist()],*[[label,*v.tolist()] for label,v in zip(labels,m)]])
        else:
            tp=m.diagonal();precision=ratio(tp,m.sum(axis=0));recall=ratio(tp,m.sum(axis=1));f1=ratio(2*tp,m.sum(axis=0)+m.sum(axis=1))
            x=np.arange(len(labels));ax.bar(x-.25,precision,.25,label='Precision');ax.bar(x,recall,.25,label='Recall');ax.bar(x+.25,f1,.25,label='F1');ax.set_xticks(x,labels,rotation=35);ax.set_ylim(0,1.05);ax.legend(frameon=False);setxy('Class','Score');save(['class','precision','recall','f1','support'],labels,precision,recall,f1,m.sum(axis=1))
    elif kind in {'model_error_hist','model_agreement','model_error_by_group','model_cook','model_leverage','model_residual_acf'}:
        if kind=='model_error_by_group':
            a,c=rows([req.x,req.y],[req.group]);err=a[1]-a[0];groups=c[0];labels=np.unique(groups);require(len(labels)<=30,'Maximum 30 groups.')
            v=[np.sqrt(np.mean(err[groups==g]**2)) for g in labels];ax.bar(range(len(labels)),v);ax.set_xticks(range(len(labels)),labels,rotation=35);setxy(req.group,'RMSE');save(['group','rmse','n'],labels,v,[int((groups==g).sum()) for g in labels])
        else:
            x,y=xy();err=y-x
            meta.update(rmse=float(np.sqrt(np.mean(err**2))),mae=float(np.mean(np.abs(err))),bias=float(err.mean()))
            if kind=='model_error_hist':
                count,edges=np.histogram(err,bins=30);ax.stairs(count,edges,fill=True,alpha=.5);ax.axvline(0,color='gray');setxy('Prediction − observation','Count');save(['lower','upper','count'],edges[:-1],edges[1:],count)
            elif kind=='model_agreement':
                ax.scatter(x,y,s=10,alpha=.5);lo=min(x.min(),y.min());hi=max(x.max(),y.max());ax.plot([lo,hi],[lo,hi],'--',color='gray',label='1:1');ax.set_aspect('equal',adjustable='box')
                if len(x)>=3 and np.ptp(x)>0:
                    fit,_,b,c=linear_fit(x,y);ax.plot([lo,hi],[b*lo+c,b*hi+c],color=palette[1],label='OLS')
                ax.legend(frameon=False);ax.text(.02,.98,f'RMSE={meta["rmse"]:.3g}\nMAE={meta["mae"]:.3g}\nBias={meta["bias"]:.3g}',transform=ax.transAxes,va='top',fontsize=8);setxy(req.x,req.y);save([req.x,req.y,'error'],x,y,err)
            elif kind=='model_residual_acf':
                require(len(x)==len(table.rows),'Residual autocorrelation requires complete ordered pairs.')
                n=int(parameter);require(n==parameter and n<len(err),'Lag must be shorter than sample.');u=err-err.mean();den=u@u;require(den>0,'Constant residuals have undefined ACF.');lags=np.arange(n+1);v=np.array([u[k:]@u[:len(u)-k]/den for k in lags]);ax.stem(lags,v);setxy('Row-order lag','Residual ACF');save(['lag','acf'],lags,v)
            else:
                fitted,residual,_,_=linear_fit(x,y);h=1/len(x)+(x-x.mean())**2/np.sum((x-x.mean())**2)
                if kind=='model_leverage':v=h;setxy('Observation index','Hat leverage')
                else:
                    mse=(residual@residual)/(len(x)-2);require(mse>0 and np.all(h<1),'Cook distance requires nonzero residual variance and leverage below one.')
                    v=residual**2/(2*mse)*h/(1-h)**2;setxy('Observation index','Cook distance')
                ax.stem(np.arange(1,len(x)+1),v);save(['row','leverage','diagnostic'],np.arange(1,len(x)+1),h,v)
    elif kind=='model_shap_summary':
        m=table_matrix(table,req,rows);v=np.mean(np.abs(m),axis=0);order=np.argsort(v);ax.barh(range(len(v)),v[order]);ax.set_yticks(range(len(v)),np.array(req.columns)[order]);setxy('Mean |supplied SHAP|','Feature');save(['feature','mean_abs_shap'],np.array(req.columns)[order],v[order])
    elif kind=='model_shap_dependence':
        x,y,z=xyz();im=ax.scatter(x,y,c=z,cmap=cmap,s=14);fig.colorbar(im,ax=ax,label=req.z);ax.axhline(0,color='gray');setxy(req.x,'Supplied SHAP contribution');save([req.x,req.y,req.z],x,y,z)
    elif kind=='model_learning':
        if req.model_validation=='spatial_blocks':
            from .studio_calibrated_models import block_regression
            require(len(set([req.x,req.y,req.z,*req.columns]))==3+len(req.columns),'Coordinates, target and regression features must be distinct.')
            a,_=rows([req.x,req.y,req.z,*req.columns]);x,y,z,*features=a
            require(len(x)==len(table.rows),'Spatial regression requires complete observations.')
            pred,fold,diagnostics=block_regression(np.column_stack((x,y)),np.column_stack(features),z,req.block_size_m,req.validation_folds,req.ridge_penalty)
            residual=pred-z
            im=ax.scatter(z,pred,c=fold,cmap='tab10',s=16,alpha=.75,vmin=.5,vmax=req.validation_folds+.5)
            fig.colorbar(im,ax=ax,label='Held-out fold',ticks=np.arange(1,req.validation_folds+1))
            lo=min(z.min(),pred.min());hi=max(z.max(),pred.max());ax.plot([lo,hi],[lo,hi],'--',color='#555555')
            setxy('Observed target','Out-of-fold prediction');meta['spatial_validation']=diagnostics
            meta['method_note']='Ridge/OLS with fold-local feature scaling; whole spatial blocks held out. Coordinates must be projected metres. Adjacent blocks can remain dependent.'
            save(['easting','northing','observed','prediction','residual','held_out_fold'],x,y,z,pred,residual,fold)
        else:
            x,y,z=xyz();order=np.argsort(x);x,y,z=x[order],y[order],z[order];require(np.all(np.diff(x)>0),'Training sizes must be unique.')
            ax.plot(x,y,label='Training');ax.plot(x,z,label='Validation');ax.legend(frameon=False);setxy(req.x,'Recorded score');save([req.x,req.y,req.z],x,y,z)
    elif kind.startswith('multi_'):
        m=table_matrix(table,req,rows);names=req.columns
        if kind in {'multi_covariance','multi_spearman'}:
            require(len(m)>1,'Multiple observations required.')
            if kind=='multi_spearman':
                a=np.column_stack([ranks(v) for v in m.T]);require(np.all(a.std(axis=0)>0),'Constant rank series.');v=np.corrcoef(a,rowvar=False)
            else:v=np.cov(m,rowvar=False)
            limit=max(np.max(np.abs(v)),1e-12);heat(v,names,'Spearman r' if kind=='multi_spearman' else 'Sample covariance','RdBu_r',-limit,limit)
            derived.extend([['feature',*names],*[[n,*a.tolist()] for n,a in zip(names,v)]])
        elif kind=='multi_distance':
            require(2<=len(m)<=300,'Distance matrix supports 2–300 complete observations.')
            sd=m.std(axis=0);require(np.all(sd>0),'Constant column cannot be standardized.');z=(m-m.mean(axis=0))/sd
            v=np.sqrt(np.maximum(0,((z[:,None,:]-z[None,:,:])**2).sum(axis=2)));im=ax.imshow(v,cmap=cmap);fig.colorbar(im,ax=ax,label='Standardized Euclidean distance');setxy('Observation','Observation')
            derived.extend([['observation',*[str(i+1) for i in range(len(m))]],*[[i+1,*a.tolist()] for i,a in enumerate(v)]])
        elif kind=='multi_vif':
            require(len(m)>len(names) and np.all(m.std(axis=0)>0),'VIF requires more observations than varying predictors.')
            z=(m-m.mean(axis=0))/m.std(axis=0);v=[]
            for j in range(len(names)):
                y=z[:,j];x=np.delete(z,j,axis=1);fit=x@np.linalg.lstsq(x,y,rcond=None)[0];res=np.sum((y-fit)**2)/np.sum(y*y);v.append(1/res if res>1e-12 else np.nan)
            require(np.isfinite(v).any(),'All VIF values undefined due to exact collinearity.')
            ax.bar(range(len(v)),v);ax.set_xticks(range(len(v)),names,rotation=35);setxy('Predictor','Variance inflation factor');save(['predictor','vif'],names,v)
        elif kind in {'multi_cluster','multi_cluster_elbow'}:
            k=int(parameter);require(k==parameter,'Cluster count must be an integer.')
            if kind=='multi_cluster':
                z,labels,sse=kmeans(m,k);score,_,_=pca(m);im=ax.scatter(score[:,0],score[:,1],c=labels,cmap='tab20',s=15);fig.colorbar(im,ax=ax,label='Cluster ID');setxy('PC1','PC2');meta['within_cluster_ss']=sse;save(['PC1','PC2','cluster'],score[:,0],score[:,1],labels+1)
            else:
                values=[kmeans(m,i)[2] for i in range(2,k+1)];ax.plot(range(2,k+1),values,marker='o');setxy('Cluster count','Within-cluster squared distance');save(['clusters','dispersion'],range(2,k+1),values)
        else:
            scores,eig,v=pca(m);fraction=eig/eig.sum()
            if kind=='multi_pca_scree':ax.bar(np.arange(1,len(eig)+1),fraction*100);setxy('Component','Explained variance (%)');save(['component','eigenvalue','fraction'],range(1,len(eig)+1),eig,fraction)
            elif kind=='multi_pca_loadings':
                load=v.T*np.sqrt(eig);im=ax.imshow(load,cmap='RdBu_r',vmin=-1,vmax=1,aspect='auto');fig.colorbar(im,ax=ax,label='Correlation loading');ax.set_yticks(range(len(names)),names);ax.set_xticks(range(len(eig)),[f'PC{i+1}' for i in range(len(eig))]);derived.extend([['feature',*[f'PC{i+1}' for i in range(len(eig))]],*[[n,*a.tolist()] for n,a in zip(names,load)]])
            else:
                ax.scatter(scores[:,0],scores[:,1],s=12,alpha=.5);setxy(f'PC1 ({fraction[0]*100:.1f}%)',f'PC2 ({fraction[1]*100:.1f}%)')
                if kind=='multi_pca_biplot':
                    load=v[:2].T*np.sqrt(eig[:2]);scale=max(np.max(np.abs(scores[:,:2])),1e-12)*.75
                    for name,(a,b) in zip(names,load):ax.annotate(name,(a*scale,b*scale),xytext=(0,0),arrowprops={'arrowstyle':'->','color':palette[1]},color=palette[1],fontsize=8)
                    meta['loading_display_scale']=float(scale);meta['loadings']=load.tolist()
                save(['PC1','PC2'],scores[:,0],scores[:,1]);meta['explained_fraction']=fraction.tolist()
    elif kind=='opt_pareto3':
        x,y,z=xyz();m=np.column_stack([-x if req.maximize_x else x,-y if req.maximize_y else y,z]);counts=domination_counts(m);mask=counts==0
        fig.delaxes(ax);ax=fig.add_subplot(111,projection='3d');ax.scatter(x[~mask],y[~mask],z[~mask],color='gray',s=12,label='Dominated');ax.scatter(x[mask],y[mask],z[mask],color=palette[1],s=22,label='Nondominated');ax.set(xlabel=req.x,ylabel=req.y,zlabel=req.z);ax.legend(frameon=False);save([req.x,req.y,req.z,'domination_count'],x,y,z,counts)
    elif kind=='opt_dominance_count':
        m=table_matrix(table,req,rows);v=domination_counts(m);ax.hist(v,bins=min(30,max(2,len(np.unique(v)))));setxy('Number of dominating candidates','Frequency');save(['candidate','domination_count'],np.arange(1,len(v)+1),v)
    elif kind=='opt_regret':
        a,c=rows(req.columns,[req.x]);labels=c[0];m=np.column_stack(a);require(len(m)<=60 and len(set(labels))==len(labels),'Maximum 60 unique scenarios.')
        v=m-m.min(axis=0);display=normalized(v);im=ax.imshow(display,aspect='auto',cmap=cmap,vmin=0,vmax=1);fig.colorbar(im,ax=ax,label='Per-objective normalized regret');ax.set_yticks(range(len(labels)),labels);ax.set_xticks(range(len(a)),req.columns,rotation=35);save([req.x,*req.columns],labels,*v.T)
    elif kind=='opt_convergence':
        x,y=xy();x,y=regular_series(x,y);v=np.maximum.accumulate(y) if req.maximize_y else np.minimum.accumulate(y);ax.plot(x,y,alpha=.3);ax.step(x,v,where='post');setxy(req.x,'Best observed objective');save([req.x,req.y,'best_so_far'],x,y,v)
    elif kind=='opt_interaction':
        x,y,z=xyz();levels=np.unique(y);require(2<=len(levels)<=12,'Choose 2–12 secondary factor levels.')
        for l in levels:
            a=x[y==l];b=z[y==l];require(len(a)>=2 and len(np.unique(a))==len(a),'Each factor level requires unique evaluated primary levels.');o=np.argsort(a);ax.plot(a[o],b[o],marker='o',label=f'{req.y}={l:g}')
        ax.legend(frameon=False);setxy(req.x,req.z);save([req.x,req.y,req.z],x,y,z)
    elif kind=='point_density':
        if req.point_mode=='voxel':
            from .studio_calibrated_models import voxel_counts
            x,y,z=xyz();centers,counts,origin=voxel_counts(x,y,z,req.voxel_size)
            fig.delaxes(ax);ax=fig.add_subplot(111,projection='3d')
            im=ax.scatter(*centers.T,c=counts,cmap=cmap,s=8+18*np.sqrt(counts/counts.max()),marker='s',alpha=.75)
            fig.colorbar(im,ax=ax,label='Points per occupied voxel',shrink=.7);ax.set(xlabel=req.x,ylabel=req.y,zlabel=req.z)
            ax.set_box_aspect(np.maximum(np.ptp(centers,axis=0),req.voxel_size))
            meta.update(voxel_size=req.voxel_size,voxel_origin=origin.tolist(),occupied_voxels=int(len(counts)),point_count=int(counts.sum()),method_note='Sparse half-open cubic bins in shared metric coordinates; square markers denote voxel centers, not reconstructed surfaces.')
            save(['x_center','y_center','z_center','point_count','points_per_cubic_unit'],*centers.T,counts,counts/req.voxel_size**3)
        else:
            x,y=xy();h,xe,ye=np.histogram2d(x,y,bins=30);im=ax.pcolormesh(xe,ye,h.T,cmap=cmap);fig.colorbar(im,ax=ax,label='Point count');ax.set_aspect('equal');setxy(req.x,req.y)
            xx,yy=np.meshgrid((xe[:-1]+xe[1:])/2,(ye[:-1]+ye[1:])/2,indexing='ij');save(['x_center','y_center','point_count'],xx.ravel(),yy.ravel(),h.ravel())
    elif kind=='point_vertical':
        a,_=rows([req.y]);v=a[0];c,e=np.histogram(v,bins=30);ax.barh((e[:-1]+e[1:])/2,c,height=np.diff(e)*.9);setxy('Point count',req.y);save(['lower','upper','count'],e[:-1],e[1:],c)
    else:raise FigureInputError('Unimplemented table domain recipe: '+kind)
    return derived
