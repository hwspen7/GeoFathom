"""Real-label evaluation pipeline with a mocked model only for CI contracts."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from vision import evaluate
from vision.quality import metrics_from_matrix,confusion_matrix


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    root=tmp_path/"models"
    root.mkdir()
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR",str(root))
    model=root/"demo.onnx"
    model.write_bytes(b"test weights, mocked runtime")
    manifest={"classes":["background","vegetation"],"bands":[1,2,3,4],
              "tile_size":128,"input_scale":255,
              "mean":[0,0,0,0],"std":[1,1,1,1]}
    (root/"demo.json").write_text(json.dumps(manifest))
    scene=tmp_path/"scene.tif"
    labels=tmp_path/"truth.tif"
    mask=np.zeros((128,128),dtype=np.uint8)
    mask[20:80,20:80]=1
    affine=from_origin(22,32,.00001,.00001)
    with rasterio.open(scene,"w",driver="GTiff",width=128,height=128,
                       count=4,dtype="uint8",crs="EPSG:4326",
                       transform=affine) as dst:
        dst.write(np.full((4,128,128),100,dtype=np.uint8))
    with rasterio.open(labels,"w",driver="GTiff",width=128,height=128,
                       count=1,dtype="uint8",crs="EPSG:4326",
                       transform=affine,nodata=255) as dst:
        dst.write(mask,1)
    return scene,labels,mask


def test_labeled_multiband_model_evaluation_reports_actual_counts(
        prepared,monkeypatch):
    scene,labels,mask=prepared
    def fake(tensor,config,device):
        assert tensor.shape==(1,4,128,128)
        assert config["classes"]==["background","vegetation"]
        return mask.copy(),np.ones((128,128),np.float32)
    monkeypatch.setattr(evaluate,"_predict_tile",fake)
    result=evaluate.evaluate_model(scene,labels,"demo",max_pixels=20000)
    assert result["overall_accuracy"]==1
    assert result["mean_iou_present_classes"]==1
    assert result["valid_pixels"]==128*128
    assert result["ignored_pixels"]==0
    assert result["confusion_matrix"]==[[128*128-3600,0],[0,3600]]
    assert len(result["image_sha256"])==64
    assert len(result["model_sha256"])==64


def test_cloud_scene_mask_excludes_training_labels(prepared,monkeypatch,tmp_path):
    scene,labels,mask=prepared
    path=tmp_path/"scl.tif"
    flags=np.full((128,128),4,dtype=np.uint8)
    flags[20:30,20:30]=9
    with rasterio.open(path,"w",driver="GTiff",width=128,height=128,
                       count=1,dtype="uint8",crs="EPSG:4326",
                       transform=from_origin(22,32,.00001,.00001)) as dst:
        dst.write(flags,1)
    monkeypatch.setattr(evaluate,"_predict_tile",
        lambda tensor,config,device: (
            mask.copy(),np.ones((128,128),np.float32)))
    result=evaluate.evaluate_model(scene,labels,"demo",scl=path)
    assert result["ignored_pixels"]==100
    assert result["valid_pixels"]==128*128-100
    assert result["overall_accuracy"]==1.
    assert result["scl_sha256"] is not None


def test_classification_rejects_out_of_range_truth():
    truth=np.array([[0,2]],dtype=np.uint8)
    prediction=np.array([[0,1]],dtype=np.uint8)
    with pytest.raises(ValueError,match="Class labels"):
        confusion_matrix(truth,prediction,2)


def test_confidence_rejection_cannot_hide_errors_from_unfiltered_report(prepared,monkeypatch):
    scene,labels,mask=prepared
    predicted=mask.copy()
    predicted[20:80,20:80]=0
    confidence=np.ones(mask.shape,np.float32)
    confidence[20:80,20:80]=.1
    monkeypatch.setattr(evaluate,"_predict_tile",lambda *args:(predicted,confidence))
    result=evaluate.evaluate_model(scene,labels,"demo",confidence=.5)
    assert result["overall_accuracy"]==1
    assert result["eligible_pixels"]==128*128
    assert result["confidence_rejected_pixels"]==3600
    assert result["unfiltered"]["overall_accuracy"]==pytest.approx((128*128-3600)/(128*128))
    assert result["accepted_fraction"]==pytest.approx((128*128-3600)/(128*128))


def test_context_halo_evaluation_scores_every_eligible_pixel_once(prepared,monkeypatch):
    scene,labels,mask=prepared
    from vision.semantic import model_directory
    manifest=model_directory()/"demo.json"
    info=json.loads(manifest.read_text());info["halo"]=16
    manifest.write_text(json.dumps(info))
    # All pixels predicted as background; every truth cell must contribute
    # exactly once regardless of the overlap and padded border.
    monkeypatch.setattr(evaluate,"_predict_tile",lambda *args:(
        np.zeros((128,128),np.uint8),np.ones((128,128),np.float32)))
    result=evaluate.evaluate_model(scene,labels,"demo")
    assert result["context_halo"]==16
    assert result["valid_pixels"]==128*128
    assert result["confusion_matrix"]==[[128*128-3600,0],[3600,0]]
