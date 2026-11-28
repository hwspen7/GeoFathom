import numpy as np
from vision.building_refinement import merge_fragments, overlap_diagnostics, hybrid_fields


def test_fragment_merge_and_wall():
    ids=np.zeros((20,30),np.int32); ids[2:18,2:20]=1; ids[7:11,20:23]=2; ids[2:7,25:30]=3
    p=(ids>0).astype(np.float32)*.9
    merged=merge_fragments(ids,p)
    assert merged[8,21]==merged[8,18] and merged[3,26]!=merged[8,18]
    np.testing.assert_array_equal(merged>0,ids>0)
    b=np.zeros_like(p); b[:,19:21]=.95
    protected=merge_fragments(ids,p,b)
    assert protected[8,21]!=protected[8,18]


def test_overlap_and_hybrid():
    ref=np.zeros((10,12),np.int32); ref[1:9,1:7]=1; ref[1:9,7:11]=2
    pred=np.zeros_like(ref); pred[1:9,1:11]=1
    assert overlap_diagnostics(pred,ref)["possible_merges"]==1
    assert overlap_diagnostics(ref,pred)["possible_splits"]==1
    valid=ref>0; a={"valid":valid,"probability":np.where(valid,.2,-1),"boundary":np.ones_like(ref)}
    b={"valid":valid,"probability":np.where(valid,.8,-1)}
    h=hybrid_fields(a,b,scale_weight=.5)
    np.testing.assert_allclose(h["probability"][valid],.5)
    assert np.all(h["probability"][~valid]==-1) and h["boundary"] is a["boundary"]


def test_empty():
    a=np.zeros((4,4),np.int32)
    assert not merge_fragments(a,a).any()
    assert overlap_diagnostics(a,a)["reference"]==0
