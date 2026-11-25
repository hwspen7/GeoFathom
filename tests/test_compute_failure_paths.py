"""Numerical fallbacks, invalid ABI metadata, and scratch lifetime contracts."""
from types import SimpleNamespace
import numpy as np
import pytest
from geometry import buffers,editing,runtime,transitions
from geometry.measure import GeometryError
from imagery import raster
from rasterio.transform import Affine
from vision import sam,trace


@pytest.mark.parametrize("mode,vertices,kw",[
    ("polygon",[[0,0],[1,1]],{}),
    ("rectangle",[[0,0]],{}),
    ("rectangle",[[0,0],[0,1]],{}),
    ("circle",[[0,0]],{"radius_m":0}),
    ("circle",[[0,0]],{"radius_m":1,"segments":8}),
    ("bearing",[[0,0]],{"bearing_deg":float("inf"),"length_m":1}),
    ("bearing",[[0,0]],{"bearing_deg":1,"length_m":100001}),
    ("unknown",[],{}),
])
def test_invalid_construction(mode,vertices,kw):
    with pytest.raises(GeometryError):
        editing.construct(mode,vertices,**kw)


@pytest.mark.parametrize("coordinate",[None,[True,0],[181,0],[0,91],[0,float("nan")],[0,0,0]])
def test_invalid_coordinate(coordinate):
    with pytest.raises(GeometryError):
        editing.coordinate(coordinate)


def test_editor_fallback_snap_simplify_and_no_match(monkeypatch):
    monkeypatch.setattr(editing,"_native",lambda:None)
    path=[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]
    assert editing.snap([.000001,.000001],[path],10)["kind"]=="vertex"
    result=editing.snap([.005,-.00001],[path],10)
    assert result["kind"]=="edge" and result["coordinate"]==pytest.approx([.005,0],abs=1e-6)
    assert not editing.snap([1,1],[path],10)["snapped"]
    assert editing.simplify([[0,0],[.005,0],[.01,0]],1)["retained"]==2
    for args in [([0,0],[[]],10),([0,0],[path],501),([0,85],[path],1)]:
        with pytest.raises(GeometryError):
            editing.snap(*args)
    with pytest.raises(GeometryError):
        editing.simplify([[0,0]],1)


def test_native_editor_rejection_is_not_silently_accepted(monkeypatch):
    def fail(*args):return -1
    monkeypatch.setattr(editing,"_native",lambda:SimpleNamespace(
        gf_snap_point=fail,gf_simplify_line=fail))
    with pytest.raises(GeometryError,match="snapping"):
        editing.snap([0,0],[[[0,0],[.01,0]]],10)
    with pytest.raises(GeometryError,match="simplification"):
        editing.simplify([[0,0],[.01,0]],1)


def test_native_cpu_runtime_failure_recovery_and_instance_identity(monkeypatch):
    for name in ("_handle","_library"):
        monkeypatch.setattr(runtime,name,None)
    calls=[]
    def create(threads):calls.append(threads);return None if len(calls)==1 else 123
    def destroy(owner):calls.append(owner)
    lib=SimpleNamespace(gf_cpu_runtime_create=create,gf_cpu_runtime_destroy=destroy)
    assert runtime.handle(SimpleNamespace()) is None
    monkeypatch.setenv("GEOFATHOM_NATIVE_THREADS","9")
    with pytest.raises(ValueError,match="1–8"):
        runtime.handle(lib)
    monkeypatch.setenv("GEOFATHOM_NATIVE_THREADS","2")
    try:
        with pytest.raises(RuntimeError,match="initialization"):
            runtime.handle(lib)
        assert runtime.handle(lib)==runtime.handle(lib)==123
        assert runtime.handle(SimpleNamespace(gf_cpu_runtime_create=create)) is None
    finally:
        runtime._close()
    assert calls==[2,2,123]


@pytest.mark.parametrize("budget",[True,63,512*1024**2+1])
def test_invalid_scratch_budget(budget):
    with pytest.raises(ValueError,match="budget"):
        buffers.ScratchPool(budget)


def test_scratch_fallback_exhaustion_exception_release_and_close(monkeypatch):
    monkeypatch.setattr(buffers,"_native",lambda:None)
    pool=buffers.ScratchPool(64)
    with pytest.raises(ValueError):
        with pool.floats((0,)):pass
    with pytest.raises(RuntimeError,match="consumer"):
        with pool.floats((16,)) as a:
            assert np.all(a==0)
            a.fill(9)
            with pytest.raises(MemoryError):
                with pool.floats((1,)):pass
            with pytest.raises(RuntimeError,match="active"):
                pool.close()
            raise RuntimeError("consumer")
    assert pool.active==0
    with pool.floats((3,)) as a:
        assert np.all(a==0)
    pool.close()
    with pytest.raises(RuntimeError,match="closed"):
        with pool.floats((1,)):pass


def test_native_scratch_allocation_rejections(monkeypatch):
    def fail(*args):return -1
    def nothing(*args):return None
    def ok(*args):return 0
    lib=SimpleNamespace(gf_buffer_pool_create=nothing,gf_buffer_pool_acquire=fail,
        gf_buffer_pool_release=ok,gf_buffer_pool_destroy=ok)
    monkeypatch.setattr(buffers,"_native",lambda:lib)
    with pytest.raises(MemoryError,match="allocation"):
        buffers.ScratchPool(64)
    lib.gf_buffer_pool_create=lambda _:123
    with buffers.ScratchPool(64) as pool:
        with pytest.raises(MemoryError,match="exhausted"):
            with pool.floats((1,)):pass
        assert not pool.active


@pytest.mark.parametrize("value",[np.zeros((2,2),np.float32),np.zeros((0,2),np.uint8),np.zeros((2,),np.uint8)])
def test_transition_invalid_input(value):
    with pytest.raises(ValueError):
        transitions.count_transitions(value)


def test_transition_fallback_and_native_error(monkeypatch):
    arr=np.array([[0,1],[1,1]],np.uint8)
    monkeypatch.setattr(transitions,"_native",lambda:None)
    assert transitions.count_transitions(arr)==2
    def fail(*args):return -1
    monkeypatch.setattr(transitions,"_native",lambda:SimpleNamespace(gf_mask_transitions=fail))
    with pytest.raises(ValueError,match="rejected"):
        transitions.count_transitions(arr)


@pytest.mark.parametrize("override,message",[
    ({"driver":"PNG"},"GeoTIFF"),({"crs":None},"reference"),
    ({"count":21},"bands"),({"width":20001},"dimensions"),
    ({"transform":Affine(0,0,0,0,0,0)},"non-invertible"),
    ({"transform":Affine.identity()},"meaningful"),
])
def test_raster_metadata_rejects_invalid_inputs(override,message):
    fields={"driver":"GTiff","crs":"EPSG:4326","count":3,"width":64,"height":64,
            "transform":Affine.translation(10,20)*Affine.scale(.001,-.001)}
    with pytest.raises(raster.RasterError,match=message):
        raster._check(SimpleNamespace(**{**fields,**override}))


def test_high_bit_depth_rgb_scaling_and_constant_bands():
    data=np.array([[[0,100],[200,1000]],[[7,7],[7,7]],
        [[np.nan,np.nan],[np.nan,np.nan]]],np.float32)
    result=raster._rgb(data)
    assert result.dtype==np.uint8 and result.shape==(2,2,3)
    assert result[0,0,0]==0 and result[1,1,0]==255
    assert not result[:,:,1:].any()


def test_trace_validation_and_sam_geometry(monkeypatch,tmp_path):
    from rasterio.transform import from_origin
    rgb=np.zeros((8,8,3),np.uint8)
    mask=np.zeros((8,8),np.uint8);mask[2:6,2:6]=1
    affine=from_origin(10,20,.0001,.0001)
    monkeypatch.setattr(trace,"read_rgb_window",lambda *a:(rgb,3,3,affine,"EPSG:4326"))
    monkeypatch.setattr(trace,"sam_mask",lambda *a:(mask,.9,"test-model"))
    result=trace.trace_raster(tmp_path/"scene.tif","id",10,20,"sam2")
    assert result["pixel_count"]==16 and result["model_id"]=="test-model"
    assert result["confidence"]==.9 and not result["window_truncated"]
    for lon,lat,provider in ((float("nan"),0,"color"),(181,0,"color"),(10,20,"unknown")):
        with pytest.raises(raster.RasterError):
            trace.trace_raster(tmp_path/"scene.tif","id",lon,lat,provider)
    mask[3,3]=0
    with pytest.raises(raster.RasterError,match="clicked point"):
        trace.trace_raster(tmp_path/"scene.tif","id",10,20,"sam2")
    with pytest.raises(raster.RasterError,match="four"):
        trace._vectorize(np.eye(2,dtype=np.uint8),affine,"EPSG:4326")


def test_zero_tolerance_exact_vertex_and_native_fallback_parity(monkeypatch):
    path=[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]
    cases=[([0,0],0),([.000001,.000001],10),([.005,-.00001],10),([1,1],10)]
    native=[editing.snap(click,[path],tolerance) for click,tolerance in cases]
    monkeypatch.setattr(editing,"_native",lambda:None)
    for (click,tolerance),expected in zip(cases,native):
        actual=editing.snap(click,[path],tolerance)
        assert actual["kind"]==expected["kind"]
        assert actual["coordinate"]==pytest.approx(expected["coordinate"],abs=1e-8)
        assert actual["distance_m"]==pytest.approx(expected["distance_m"],abs=1e-7) if expected["distance_m"] is not None else actual["distance_m"] is None
    assert editing.snap([0,0],[path],0)["snapped"]


def test_raster_structure_precedes_optional_tags_and_scientific_band_extension():
    fields={'driver':'GTiff','crs':'EPSG:4326','count':3,'width':64,'height':64,
            'transform':Affine.translation(10,20) @ Affine.scale(.001,-.001)}
    def unreadable():raise AssertionError('Optional tags must not precede structural validation.')
    for override,message in [({'width':20001},'dimensions'),({'transform':Affine.identity()},'meaningful'),
                             ({'count':0},'bands'),({'count':1025},'bands')]:
        with pytest.raises(raster.RasterError,match=message):
            raster._check(SimpleNamespace(**{**fields,**override,'tags':unreadable}))
    raster._check(SimpleNamespace(**{**fields,'tags':unreadable}))
    for schema in ('geofathom-optical-cube-1','geofathom-rf-prediction-1'):
        raster._check(SimpleNamespace(**{**fields,'count':32,'tags':lambda:{'REMOTE_SCHEMA':schema}}))
    with pytest.raises(raster.RasterError,match='supported scientific schema'):
        raster._check(SimpleNamespace(**{**fields,'count':32,'tags':lambda:{'REMOTE_SCHEMA':'unknown'}}))
