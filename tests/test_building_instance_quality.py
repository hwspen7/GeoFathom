import numpy as np
from shapely.geometry import box,Polygon
from rasterio.transform import Affine
from vision.building_outline import fitted_outline
from vision.building_instance_quality import instance_records,ranked_metrics


def test_perfect_quality_and_empty_predictions():
    ids=np.zeros((16,20),np.int32); ids[2:8,2:8]=3; ids[9:15,12:19]=9
    p=(ids>0).astype(np.float32)*.9
    r=instance_records(ids,ids,p)
    m=ranked_metrics([r])
    assert m["ap50"]==m["ap75"]==m["pq"]==m["sq"]==m["rq"]==1.
    assert all(x["best_match"]["centroid_error_pixels"]==0 for x in r["predictions"])
    empty=ranked_metrics([instance_records(np.zeros_like(ids),ids,p)])
    assert empty["ap50"]==empty["pq"]==0


def test_ranking_penalizes_early_false_positive():
    scenes=[{"references":[{}],"predictions":[{"id":0,"score":.9,"overlaps":[]},{"id":1,"score":.8,"overlaps":[(0,1.)]}]}]
    r=ranked_metrics(scenes)
    assert r["ap50"]==.5 and r["pq"]==2/3


def test_guarded_fit_no_outward_area_or_hole_loss():
    g=Polygon([(0,0),(8,0),(8,8),(0,8)],holes=[[(2,2),(4,2),(4,4),(2,4)]])
    refined,_=fitted_outline(g,Affine.identity())
    assert refined.is_valid and len(refined.interiors)==1
    assert refined.difference(g).area<=1e-8
    assert refined.equals(g)
