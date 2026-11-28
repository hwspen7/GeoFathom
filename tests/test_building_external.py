import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from vision.building_external import (CATALOG,windows,coco_polygons,native_instances,
    write_prediction,read_prediction,match_instances,supported_instances,vector_consensus)


def record(x0,y0,x1,y1,score=1.):
    return {"rings":[[x0,y0,x1,y0,x1,y1,x0,y1]],"score":score}


def test_windows_cover_native_shape():
    a=np.zeros((509,711),bool)
    for y,x,h,w in windows(a.shape,224,168):
        a[y:y+h,x:x+w]=True
    assert a.all()
    assert windows((32,64),512,384)==[(0,0,32,64)]


def test_native_instances_conflict_and_invalid():
    ids,d=native_instances([record(0,0,10,10,.9),record(8,0,18,10,.8),
        {"rings":[[0,0,8,8,0,8,8,0]],"score":.7}],(20,20))
    assert d["accepted"]==2 and d["invalid_rings"]==1
    assert d["overlap_pixels_counted_with_multiplicity"]==20
    assert (ids==1).sum()==100 and (ids==2).sum()==80
    assert ids[3,9]==1 and ids[3,11]==2
    with pytest.raises(ValueError,match="identity"):
        coco_polygons([{"image_id":"wrong","segmentation":[]}],"right")


def test_matching_support_and_consensus():
    a=np.zeros((32,32),np.int32);b=a.copy()
    a[2:12,2:12]=1;a[16:24,2:12]=2
    b[2:12,3:13]=1;b[16:24,16:24]=2
    field={"valid":np.ones(a.shape,bool),"probability":np.zeros(a.shape,np.float32)}
    field["probability"][b==2]=.9
    assert match_instances(a,b)==[{"primary":1,"secondary":1,"iou":90/110}]
    assert not supported_instances(a,field).any()
    out,d=vector_consensus(a,b,field)
    assert d["matched"]==1 and d["added"]==1
    assert (out==1).sum()==100 and not out[18,3] and out[18,18]>0


@pytest.mark.parametrize("name",["unibuild","sampolybuild","pix2poly"])
def test_prediction_native_receipt_and_tamper(tmp_path,name):
    source=tmp_path/"source.tif"
    with rasterio.open(source,"w",driver="GTiff",width=32,height=24,count=3,dtype="uint8",
                       crs="EPSG:32617",transform=from_origin(500000,4500000,1,1)) as dst:
        dst.write(np.ones((3,24,32),np.uint8))
    identity={"name":name,"revision":CATALOG[name]["revision"],"checkpoint_sha256":"a"*64}
    payload=np.full((24,32),.7,np.float32) if name=="unibuild" else [record(2,2,10,10)]
    path=tmp_path/"pred"
    m=write_prediction(path,source,name,payload,identity,{"split":"validation"})
    field,ids,receipt=read_prediction(path,source,name)
    assert receipt==m and field["valid"].all()
    if ids is not None:
        assert (ids>0).sum()==64 and field["probability"].sum()==64
    else:
        np.testing.assert_allclose(field["probability"],.7)
    with (path/m["data"]).open("ab") as out:
        out.write(b"changed")
    with pytest.raises(ValueError,match="provenance"):
        read_prediction(path,source,name)


def test_candidate_grid_no_fake_model():
    from scripts.building_external_study import recipes
    r=recipes(["unibuild","sampolybuild","pix2poly"])
    assert r[0]["name"]=="baseline" and len(r)==51
    assert any(x["kind"]=="consensus" for x in r)
    assert all(x["name"] in ("baseline","unibuild") for x in recipes(["unibuild"]))


def test_unibuild_export_probability_gate():
    from scripts.building_unibuild_export import parity
    p=np.full((1,1,512,512),.8,np.float32)
    assert parity(p,p+.0001)["passed"]
    with pytest.raises(ValueError,match="parity"):
        parity(p,p-.01)
    p[0,0,0,0]=np.nan
    with pytest.raises(ValueError,match="Invalid"):
        parity(p,p)


def test_native_export_keeps_original_grid(tmp_path):
    from scripts.building_external_study import export_native
    src=tmp_path/"source.tif"
    transform=from_origin(500000,4500000,2,2)
    with rasterio.open(src,"w",driver="GTiff",width=32,height=24,count=3,dtype="uint8",
                       crs="EPSG:32617",transform=transform) as dst:
        dst.write(np.ones((3,24,32),np.uint8))
    ids=np.zeros((24,32),np.int32);ids[2:8,4:10]=1
    fields={"valid":np.ones(ids.shape,bool),"probability":(ids>0).astype(np.float32)}
    path=tmp_path/"result"
    export_native(path,{"paths":{"image":src}},ids,fields,{"kind":"native_instances"})
    with rasterio.open(path/"instances.tif") as ds:
        assert ds.transform==transform and ds.crs.to_epsg()==32617
        np.testing.assert_array_equal(ds.read(1),ids)
    assert not (path/"probability.tif").exists()
    data=json.loads((path/"footprints.json").read_text())
    assert data["coordinate_space"]=="native_crs" and data["features"][0]["properties"]["instance_id"]==1


def test_pix_encoder_cache_reuses_only_same_image_and_restores():
    import torch
    from torch import nn
    from vision.building_pix2poly import cached_encoder
    class Encoder(nn.Module):
        def __init__(self):
            super().__init__();self.calls=0
        def forward(self,x):
            self.calls+=1;return x*2
    class Decoder(nn.Module):
        def predict(self,features,tokens):
            return features+tokens,features
    class Model(nn.Module):
        def __init__(self):
            super().__init__();self.encoder=Encoder();self.decoder=Decoder()
        def predict(self,x,tokens):
            return self.decoder.predict(self.encoder(x),tokens)
    model=Model().eval();x=torch.ones(1,2);t=torch.ones(1,2)
    with torch.no_grad():
        expected=model.predict(x,t);model.encoder.calls=0
        with cached_encoder(model,x):
            for _ in range(4):
                actual=model.predict(x,t)
                torch.testing.assert_close(actual[0],expected[0])
            assert model.encoder.calls==1
            with pytest.raises(ValueError,match="another image"):
                model.predict(x.clone(),t)
        model.predict(x,t)
        assert model.encoder.calls==2
        with pytest.raises(RuntimeError):
            with cached_encoder(model,x):
                raise RuntimeError("test")
        assert model.predict.__func__ is Model.predict


def test_pix_variant_config_capacity():
    from types import SimpleNamespace
    from vision.building_pix2poly import configure_variant
    c=SimpleNamespace(INPUT_HEIGHT=224,INPUT_WIDTH=224,PATCH_SIZE=8,NUM_BINS=224)
    configure_variant(c,"whu")
    assert (c.N_VERTICES,c.MAX_LEN,c.generation_steps)==(144,290,289)
    configure_variant(c,"spacenet")
    assert (c.N_VERTICES,c.MAX_LEN,c.generation_steps)==(192,386,385)
