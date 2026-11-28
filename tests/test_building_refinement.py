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


def test_joint_ridge_and_mask():
    from vision.building_refinement import joint_ridge, refine_mask
    p=np.zeros((9,9),np.float32); p[2:7,2:7]=.9; p[4,4]=.3; p[1,4]=.3
    valid=np.ones_like(p,bool); valid[0,:]=False
    b=np.zeros_like(p); b[2,3]=.95
    ridge=joint_ridge(p,b,None,valid)
    assert ridge[2,3]==b[2,3] and 0<ridge[4,4]<.5 and not ridge[0].any()
    m=refine_mask(p,valid,.35,b)
    assert not m[4,4] and not m[0].any()


def test_group_crossfit():
    from vision.building_refinement import grouped_temperature_nll
    from types import SimpleNamespace
    a=SimpleNamespace(losses=np.array([1.,2.,3.]),count=10,positive=5)
    b=SimpleNamespace(losses=np.array([3.,2.,1.]),count=10,positive=5)
    r=grouped_temperature_nll({"a":a,"b":b},(.5,1.,2.))
    assert r["evaluated"] and r["raw_nll"]==.2 and r["crossfit_nll"]==.3


def test_spatial_consistency_fusion():
    from vision.building_refinement import spatial_view_fusion
    valid=np.ones((12,12),bool); valid[0]=False

    def f(v):
        return {"valid":valid,"probability":np.where(valid,v,-1).astype(np.float32)}

    a=f(.9); z=f(.1); b=f(.8)
    h=spatial_view_fusion(a,z,b,b)
    equal=(.65*.9+.35*.1+.8)/2
    assert np.all(h["probability"][valid]>equal)
    assert np.all(h["probability"][valid]<=.8) and np.all(h["probability"][~valid]==-1)
    np.testing.assert_allclose(spatial_view_fusion(a,a,b,b)["probability"][valid],.85,atol=1e-7)
