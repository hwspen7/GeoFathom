"""Ranked instance metrics and per-object geometry evidence on the source grid."""
import numpy as np


def instance_records(predicted_ids, reference_ids, probability):
    """Sparse per-object overlap graph; raw mean probability is only a score.

    Polygonization uses the same 4-connected support and minimum size as the
    study. Geometry errors are in source pixels, never invented ground units.
    """
    from rasterio.features import shapes
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    from .building_outline import fitted_outline

    def polygons(ids, minimum):
        result=[]
        for geom,value in shapes(np.asarray(ids,np.int32),mask=ids>0,connectivity=4):
            g=shape(geom)
            if g.area>=minimum:
                if not g.is_valid:
                    raise ValueError("Invalid instance geometry.")
                result.append((int(value),g))
        if len(result)>20000:
            raise ValueError("Instance quality budget exceeded.")
        return result

    pred=polygons(predicted_ids,9); truth=polygons(reference_ids,1)
    refs=[g for _,g in truth]; tree=STRtree(refs)
    out=[]; best=[0.]*len(refs); edges=0
    for idx,(label,g) in enumerate(pred):
        left,top,right,bottom=map(int,g.bounds)
        cells=rasterize([(g,1)],out_shape=(bottom-top,right-left),transform=Affine.translation(left,top)).astype(bool)
        confidence=float(np.mean(probability[top:bottom,left:right][cells]))
        refined,status=fitted_outline(g,Affine.identity())
        candidates=[]
        for j in tree.query(g,predicate="intersects"):
            j=int(j); t=refs[j]; intersection=g.intersection(t).area
            if intersection<=0:
                continue
            iou=intersection/(g.area+t.area-intersection)
            best[j]=max(best[j],iou)
            candidates.append((j,iou)); edges+=1
            if edges>1_000_000:
                raise ValueError("Instance overlap graph exceeds budget.")
        candidates.sort(key=lambda x:(-x[1],x[0]))
        row={"id":idx,"label":label,"score":confidence,"area_pixels":float(g.area),
             "centroid_pixels":[float(g.centroid.x),float(g.centroid.y)],"overlaps":candidates,
             "outline_status":status["outline_status"],"best_match":None}
        if candidates:
            j,iou=candidates[0]; t=refs[j]
            inter=g.intersection(t).area; fitted_inter=refined.intersection(t).area
            row["best_match"]={"reference_index":j,"iou":iou,"reference_coverage":inter/t.area,
                "prediction_coverage":inter/g.area,"relative_area_error":(g.area-t.area)/t.area,
                "centroid_error_pixels":g.centroid.distance(t.centroid),
                "boundary_hausdorff_pixels":g.boundary.hausdorff_distance(t.boundary),
                "fitted_iou":fitted_inter/(refined.area+t.area-fitted_inter)}
        out.append(row)
    return {"predictions":out,"references":[{"id":i,"label":label,"area_pixels":float(g.area),
                "centroid_pixels":[float(g.centroid.x),float(g.centroid.y)],"best_iou":best[i]}
                for i,(label,g) in enumerate(truth)],"confidence_calibrated":False}


def ranked_metrics(scenes):
    """Dataset-wide interpolated AP and strict-IoU panoptic quality.

    AP is 101-point interpolated precision at fixed mask IoU thresholds, no
    crowd/ignore-area COCO protocol. PQ uses >.5 unique nonoverlapping matches.
    """
    total=sum(len(s["references"]) for s in scenes)
    predictions=sorted(((float(p["score"]),i,p) for i,s in enumerate(scenes) for p in s["predictions"]),
                       key=lambda x:(-x[0],x[1],x[2]["id"]))
    result={}
    for threshold in (.5,.75):
        used=set(); flags=[]
        for _,i,p in predictions:
            match=next((j for j,v in p["overlaps"] if v>=threshold and (i,j) not in used),None)
            flags.append(match is not None)
            if match is not None:
                used.add((i,match))
        tp=np.cumsum(flags,dtype=float)
        recall=tp/max(total,1)
        precision=tp/np.arange(1,len(flags)+1)
        result["ap"+str(int(threshold*100))]=float(np.mean([
            np.max(precision[recall>=r],initial=0.) for r in np.linspace(0,1,101)])) if total else None
    matches=[v for _,_,p in predictions for _,v in p["overlaps"] if v>.5]
    tp=len(matches); denom=.5*(len(predictions)+total)
    result.update({"pq":float(sum(matches)/denom) if denom else None,
                   "sq":float(np.mean(matches)) if matches else None,
                   "rq":float(tp/denom) if denom else None,"pq_matches":tp,
                   "reference_count":total,"prediction_count":len(predictions)})
    return result


def crossfit_object_quality(scenes):
    """Grouped Platt fit for best-overlap IoU >= .5; not one-to-one correctness."""
    from scipy.special import expit
    from scipy.optimize import minimize
    rows=[]
    for group,scene in scenes:
        for p in scene["predictions"]:
            target=float(bool(p["best_match"] and p["best_match"]["iou"]>=.5))
            score=np.clip(float(p["score"]),1e-6,1-1e-6)
            rows.append((group,float(np.log(score/(1-score))),target))
    groups=sorted({r[0] for r in rows})
    if len(groups)<2 or len({r[2] for r in rows})<2:
        return {"evaluated":False,"reason":"Need two source groups and both outcome classes."}

    def fit(data):
        x=np.array([r[1] for r in data]); y=np.array([r[2] for r in data])
        if len(np.unique(y))<2:
            return None
        def objective(beta):
            z=beta[0]*x+beta[1]
            return float(np.mean(np.logaddexp(0,z)-y*z)+.001*((beta[0]-1)**2+beta[1]**2))
        result=minimize(objective,[1.,0.],bounds=[(0.,8.),(-8.,8.)],method="L-BFGS-B")
        return result.x if result.success and np.isfinite(result.x).all() else None

    raw=[];calibrated=[];truth=[]
    for group in groups:
        beta=fit([r for r in rows if r[0]!=group])
        if beta is None:
            return {"evaluated":False,"reason":"A source-group fold has insufficient outcomes or failed fit."}
        for g,x,y in rows:
            if g==group:
                raw.append(float(expit(x)));calibrated.append(float(expit(beta[0]*x+beta[1])));truth.append(y)
    beta=fit(rows)
    if beta is None:
        return {"evaluated":False,"reason":"Full validation fit failed."}
    y=np.asarray(truth);a=np.asarray(raw);b=np.asarray(calibrated)
    return {"evaluated":True,"groups":len(groups),"objects":len(y),
            "raw_brier":float(np.mean((a-y)**2)),"crossfit_brier":float(np.mean((b-y)**2)),
            "slope":float(beta[0]),"intercept":float(beta[1]),
            "target":"best overlap IoU >= .5; not unique matching or surveyed quality",
            "qualification":"validation only"}
