"""Multi-tile batch contract and independently generated ONNX CPU inference."""
import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from vision import semantic
from vision.tiled import semantic_segmentation_tiled

def test_streaming_batch_and_tail(tmp_path,monkeypatch):
    root=tmp_path/"models";root.mkdir()
    (root/"batch.onnx").write_bytes(b"mock")
    (root/"batch.json").write_text(json.dumps({"classes":["background","target"],
        "bands":[1],"tile_size":128,"halo":16,"max_batch":3,"input_scale":100}))
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR",str(root))
    seen=[]
    def batch(tensor,config,device):
        seen.append(len(tensor))
        n,_,h,w=tensor.shape
        return np.ones((n,h,w),np.uint8),np.ones((n,h,w),np.float32)
    monkeypatch.setattr(semantic,"_predict_batch",batch)
    p=tmp_path/"image.tif"
    with rasterio.open(p,"w",driver="GTiff",width=385,height=97,count=1,dtype="uint8",
        crs="EPSG:4326",transform=from_origin(10,30,.00001,.00001)) as ds:
        ds.write(np.full((1,97,385),100,np.uint8))
    result=semantic_segmentation_tiled(p,"x","batch",memory_mb=32)
    assert result["classified_pixels"]==385*97
    assert result["tile_count"]==10
    assert result["batch_size"]==3
    assert seen==[3,3,3,1]

def test_real_onnx_cpu_batch(tmp_path,monkeypatch):
    onnx=pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import TensorProto,helper
    root=tmp_path/"real";root.mkdir()
    # Dynamic N, two class logits: class 1 wins for every positive pixel.
    x=helper.make_tensor_value_info("x",TensorProto.FLOAT,["N",1,128,128])
    y=helper.make_tensor_value_info("y",TensorProto.FLOAT,["N",2,128,128])
    neg=helper.make_node("Neg",["x"],["negative"])
    concat=helper.make_node("Concat",["negative","x"],["y"],axis=1)
    model=helper.make_model(helper.make_graph([neg,concat],"batch-test",[x],[y]),
                            opset_imports=[helper.make_opsetid("",13)],ir_version=8)
    onnx.save(model,str(root/"real.onnx"))
    (root/"real.json").write_text(json.dumps({"classes":["background","target"],
         "bands":[1],"tile_size":128,"max_batch":3}))
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR",str(root))
    config=semantic._manifest("real")
    values=np.ones((3,1,128,128),np.float32)
    values[1]*=-1
    labels,confidence=semantic._predict_batch(values,config,"cpu")
    assert labels.shape==(3,128,128)
    assert labels[0].all() and not labels[1].any() and labels[2].all()
    np.testing.assert_allclose(confidence,1/(1+np.exp(-2)),rtol=1e-6)
