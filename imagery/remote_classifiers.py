"""Spatially blocked classification using established scikit-learn estimators."""
import numpy as np
from analysis.science_raster import require
from .remote_partitions import spatial_partitions

def blocked_classifier(v,grid,p,kind):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.svm import SVC
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.metrics import confusion_matrix
    import sklearn
    stack=np.stack([v[k] for k in ('blue','green','red','nir')]);labels=v['training']
    valid=np.isfinite(stack).all(axis=0);labeled=valid&np.isfinite(labels)&(labels>0)
    require(grid.is_meter,'Spatial cross-validation requires a projected metre grid.')
    require(20<=labeled.sum()<=10000 and valid.sum()<=500000,'Use 20–10,000 labeled and at most 500,000 complete cells.')
    if kind=='spatial_svm_cv':require(labeled.sum()<=4000 and valid.sum()<=100000,'RBF SVM exceeds work budget.')
    folds=p['folds'];fold,excluded=spatial_partitions(valid.shape,grid.transform,p['block_m'],folds,p['buffer_blocks'])
    classes=np.unique(labels[labeled])
    require(2<=len(classes)<=32,'Use 2–32 labeled classes.')
    if kind=='spatial_rf_cv':require(int(valid.sum())*p['trees']<=25_000_000,'Forest inference exceeds work budget.')
    def estimator():
        if kind=='spatial_rf_cv':
            return RandomForestClassifier(n_estimators=p['trees'],max_depth=p['max_depth'],min_samples_leaf=p['min_leaf'],
                                          random_state=p['seed'],n_jobs=1,class_weight='balanced')
        if kind=='spatial_svm_cv':
            return make_pipeline(StandardScaler(),SVC(C=p['c'],gamma=p['gamma'],class_weight='balanced',cache_size=128))
        return LinearDiscriminantAnalysis(solver='lsqr',shrinkage=p['shrinkage'],priors=np.full(len(classes),1/len(classes)))
    oof=np.full(valid.shape,np.nan);rows=[];mat=np.zeros((len(classes),len(classes)),dtype=np.int64)
    for j in range(folds):
        hold=labeled&(fold==j);train=labeled&~excluded[j]
        require(not np.any(train&hold),'Spatial partition overlap.')
        require(all(np.count_nonzero(train&(labels==c))>=5 and np.count_nonzero(hold&(labels==c))>=1 for c in classes),
                'Each spatial fold needs five training and one validation cell per class; adjust block size or labels.')
        model=estimator();model.fit(stack[:,train].T,labels[train]);pred=model.predict(stack[:,hold].T)
        oof[hold]=pred;cm=confusion_matrix(labels[hold],pred,labels=classes);mat+=cm
        recall=np.diag(cm)/cm.sum(axis=1)
        rows.append([j,int(train.sum()),int(hold.sum()),int((labeled&~train&~hold).sum()),float(np.trace(cm)/cm.sum()),float(recall.mean())])
    require(np.isfinite(oof[labeled]).all(),'Every labeled observation must receive one held-out prediction.')
    # Final fit uses all labels for the deployable map. Metrics come only from OOF.
    model=estimator();model.fit(stack[:,labeled].T,labels[labeled])
    out=np.full(valid.shape,np.nan);x=stack[:,valid].T;prediction=np.empty(len(x))
    for start in range(0,len(x),4096):prediction[start:start+4096]=model.predict(x[start:start+4096])
    out[valid]=prediction
    support=mat.sum(axis=1);predicted=mat.sum(axis=0);diag=np.diag(mat);n=int(mat.sum())
    recall=diag/support;precision=np.divide(diag,predicted,out=np.zeros(len(classes)),where=predicted>0)
    f1=np.divide(2*precision*recall,precision+recall,out=np.zeros(len(classes)),where=precision+recall>0)
    expected=float((support/n)@(predicted/n));oa=float(diag.sum()/n)
    metrics={'estimator':kind,'sklearn_version':sklearn.__version__,'classes':classes.astype(int).tolist(),
             'oof_confusion_matrix_reference_rows':mat.tolist(),'oof_cells':n,'oof_overall_accuracy':oa,
             'oof_balanced_accuracy':float(recall.mean()),'oof_macro_f1':float(f1.mean()),
             'oof_kappa':(oa-expected)/(1-expected) if expected<1 else None,
             'oof_precision':precision.tolist(),'oof_recall':recall.tolist(),'folds':folds,'partition':'recursive_spatial_blocks','block_m':p['block_m'],
             'buffer_blocks':p['buffer_blocks'],'interpretation':'OOF metrics from fixed hyperparameters and spatial blocks; final map refits all labels. Not nested tuning or external-site validation.'}
    if kind=='spatial_rf_cv':metrics['final_impurity_feature_importance']=model.feature_importances_.tolist()
    return out,['fold','training_cells','validation_cells','buffer_excluded','accuracy','balanced_accuracy'],rows,metrics


def nested_svm(v,grid,p):
    """Nested spatial CV. Outer holdouts are never used in hyperparameter selection."""
    from sklearn.svm import SVC
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import balanced_accuracy_score,confusion_matrix
    import sklearn
    stack=np.stack([v[k] for k in ('blue','green','red','nir')]);labels=v['training']
    valid=np.isfinite(stack).all(axis=0);labeled=valid&np.isfinite(labels)&(labels>0)
    require(grid.is_meter,'Spatial nested validation requires a projected metre grid.')
    require(40<=labeled.sum()<=3000 and valid.sum()<=100000,'Nested SVM requires 40–3,000 labels and at most 100,000 complete cells.')
    folds=p['folds'];fold,excluded=spatial_partitions(valid.shape,grid.transform,p['block_m'],folds,p['buffer_blocks'])
    classes=np.unique(labels[labeled])
    require(2<=len(classes)<=32,'Use 2–32 labeled classes.')
    # All inner and outer fits share label-independent spatial buffers.
    def build(c):return make_pipeline(StandardScaler(),SVC(C=c,gamma=p['gamma'],class_weight='balanced',cache_size=128))
    candidates=[p['c']/10,p['c'],p['c']*10]
    def check(train,hold):
        require(not np.any(train&hold) and all(np.count_nonzero(train&(labels==c))>=5 and np.count_nonzero(hold&(labels==c))>=1 for c in classes),
                'Each nested spatial split needs five training and one validation cell per class.')
    def select(pool,indices):
        scores=[]
        for c in candidates:
            acc=[]
            for k in indices:
                hold=pool&(fold==k);train=pool&~excluded[k];check(train,hold)
                model=build(c);model.fit(stack[:,train].T,labels[train])
                acc.append(float(balanced_accuracy_score(labels[hold],model.predict(stack[:,hold].T))))
            scores.append(float(np.mean(acc)))
        return candidates[int(np.argmax(scores))],scores
    mat=np.zeros((len(classes),len(classes)),int);rows=[]
    for j in range(folds):
        hold=labeled&(fold==j);train=labeled&~excluded[j];check(train,hold)
        best,scores=select(train,[k for k in range(folds) if k!=j])
        model=build(best);model.fit(stack[:,train].T,labels[train]);pred=model.predict(stack[:,hold].T)
        cm=confusion_matrix(labels[hold],pred,labels=classes);mat+=cm
        rows.append([j,int(train.sum()),int(hold.sum()),best,max(scores),float(np.trace(cm)/cm.sum()),float(np.mean(np.diag(cm)/cm.sum(axis=1)))])
    require(mat.sum()==labeled.sum(),'Outer OOF coverage mismatch.')
    best,scores=select(labeled,list(range(folds)));model=build(best);model.fit(stack[:,labeled].T,labels[labeled])
    out=np.full(valid.shape,np.nan);x=stack[:,valid].T;prediction=np.empty(len(x))
    for i in range(0,len(x),4096):prediction[i:i+4096]=model.predict(x[i:i+4096])
    out[valid]=prediction
    support=mat.sum(axis=1);predicted=mat.sum(axis=0);diag=np.diag(mat);n=int(mat.sum())
    recall=diag/support;precision=np.divide(diag,predicted,out=np.zeros(len(classes)),where=predicted>0)
    f1=np.divide(2*precision*recall,precision+recall,out=np.zeros(len(classes)),where=precision+recall>0)
    return out,['fold','training_cells','validation_cells','selected_c','inner_balanced_accuracy','accuracy','balanced_accuracy'],rows,{
        'classes':classes.astype(int).tolist(),'oof_confusion_matrix_reference_rows':mat.tolist(),'oof_cells':n,
        'oof_overall_accuracy':float(diag.sum()/n),'oof_balanced_accuracy':float(recall.mean()),'oof_macro_f1':float(f1.mean()),
        'partition':'recursive_spatial_blocks','buffer_blocks':p['buffer_blocks'],'candidate_c':candidates,'final_selected_c':best,'final_inner_scores':scores,'sklearn_version':sklearn.__version__,
        'interpretation':'Outer folds evaluate independently tuned models. Final model tuned on all spatial folds then refit; no external-site accuracy claim.'}
