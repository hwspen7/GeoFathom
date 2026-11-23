"""Full-resolution streamed raster analysis and job integration regressions."""
import time

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from core.main import app
from imagery.raster import RasterError
from vision.geoai import spectral_index
from vision.tiled import TilePlan, spectral_change_tiled, spectral_index_tiled

client = TestClient(app)
AFFINE = from_origin(120, 32, .00001, .00001)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH", str(tmp_path / "tiled.sqlite"))
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "tile-admin")


def raster(tmp_path, name, changed=False, nodata=False, transform=AFFINE):
    path=tmp_path/name
    data=np.full((4, 128, 128), 100, dtype=np.uint16)
    if changed:
        data[0,24:96,28:100]=50
        data[3,24:96,28:100]=200
    if nodata:
        data[:,40:44,48:52]=0
    with rasterio.open(path,"w",driver="GTiff",width=128,height=128,
                       count=4,dtype="uint16",nodata=0 if nodata else None,
                       crs="EPSG:4326",transform=transform) as dst:
        dst.write(data)
    return path


def test_plan_bounds_memory_budget_and_row_major_tile_coverage():
    plan=TilePlan(130,70,tile_size=64,max_pixels=15000,memory_mb=8)
    windows=list(plan.windows())
    assert len(windows)==6
    assert windows[0].col_off==0 and windows[0].row_off==0
    assert windows[-1].width==2 and windows[-1].height==6
    assert sum(int(w.width*w.height) for w in windows)==130*70
    with pytest.raises(RasterError,match="pixel count"):
        TilePlan(130,70,tile_size=64,max_pixels=9000)
    with pytest.raises(RasterError,match="memory allowance"):
        TilePlan(512,512,tile_size=512,memory_mb=4)
    with pytest.raises(RasterError):
        TilePlan(512,512,tile_size=10)
    with pytest.raises(RasterError):
        TilePlan(512,512,memory_mb=True)


def test_tiled_spectral_polygon_merges_across_tile_seams(tmp_path):
    path=raster(tmp_path,"vegetation.tif",changed=True)
    markers=[]
    tiled=spectral_index_tiled(
        path,"image","ndvi",4,1,.3,tile_size=64,
        max_pixels=20000,memory_mb=8,progress=markers.append)
    reference=spectral_index(path,"image","ndvi",4,1,.3,max_side=128)
    assert tiled["pixel_grid"]==[128,128]
    assert tiled["tile_count"]==4
    assert tiled["classified_pixels"]==72*72
    assert tiled["valid_pixels"]==128*128
    assert len(tiled["features"])==1
    assert tiled["features"][0]["properties"]["pixel_count"]==72*72
    assert tiled["features"][0]["properties"]["area_m2"]==pytest.approx(
        reference["features"][0]["properties"]["area_m2"],rel=.005)
    assert tiled["features"][0]["properties"]["quality"]=="requires_user_review"
    assert tiled["engine"].endswith(("cpp-spectral","numpy-spectral"))
    assert markers[0]==0 and markers[-1]==1
    assert all(a<=b for a,b in zip(markers,markers[1:]))


def test_tiled_spectral_nodata_and_cancellation(tmp_path):
    path=raster(tmp_path,"masked.tif",changed=True,nodata=True)
    tiled=spectral_index_tiled(path,"image","ndvi",4,1,.3,
                               tile_size=64,memory_mb=8)
    assert tiled["valid_pixels"]==128*128-16
    assert tiled["classified_pixels"]==72*72-16
    assert tiled["features"][0]["geometry"]["type"]=="Polygon"
    def cancelled(fraction):
        if fraction>=.25:
            raise RuntimeError("Cancelled at a tile boundary.")
    with pytest.raises(RuntimeError,match="Cancelled"):
        spectral_index_tiled(path,"image","ndvi",4,1,.3,
                             tile_size=64,memory_mb=8,progress=cancelled)


def test_tiled_temporal_change_preserves_cross_tile_connectivity(tmp_path):
    before=raster(tmp_path,"before.tif")
    after=raster(tmp_path,"after.tif",changed=True)
    gain=spectral_change_tiled(
        before,after,"before","after",4,1,.2,
        tile_size=64,memory_mb=8)
    assert gain["gain_pixels"]==72*72
    assert gain["loss_pixels"]==0
    assert gain["valid_pixels"]==128*128
    assert len(gain["features"])==1
    assert gain["features"][0]["properties"]["class_name"]=="index_gain"
    loss=spectral_change_tiled(
        after,before,"after","before",4,1,.2,
        tile_size=64,memory_mb=8)
    assert loss["loss_pixels"]==72*72
    assert loss["gain_pixels"]==0
    assert len(loss["features"])==1
    with pytest.raises(RasterError,match="overlapping"):
        different=raster(tmp_path,"far.tif",changed=True,
                        transform=from_origin(100,20,.00001,.00001))
        spectral_change_tiled(before,different,"before","far",4,1,
                              tile_size=64,memory_mb=8)


def test_streamed_analysis_is_background_job_with_progress(tmp_path):
    path=raster(tmp_path,"upload.tif",changed=True)
    image=client.post("/imagery/upload",
       files={"file":("upload.tif",path.read_bytes(),"image/tiff")},
       headers={"X-GeoFathom-Admin-Token":"tile-admin"})
    assert image.status_code==201,image.text
    project=client.post("/projects",json={"name":"Streamed raster"}).json()["id"]
    payload={"image_id":image.json()["id"],"index":"ndvi",
             "first_band":4,"second_band":1,"threshold":.3,
             "full_resolution":True,"tile_size":64,
             "max_pixels":20000,"memory_mb":8}
    denied=client.post(f"/projects/{project}/jobs",
                       json={"kind":"spectral_index","payload":payload})
    assert denied.status_code==403
    created=client.post(f"/projects/{project}/jobs",
                       json={"kind":"spectral_index","payload":payload},
                       headers={"X-GeoFathom-Admin-Token":"tile-admin"})
    assert created.status_code==202,created.text
    uid=created.json()["id"]
    stop=time.monotonic()+12
    while time.monotonic()<stop:
        job=client.get(f"/projects/{project}/jobs/{uid}").json()
        if job["status"] in {"completed","failed","cancelled","interrupted"}:
            break
        time.sleep(.03)
    assert job["status"]=="completed",job
    assert job["progress"]==100
    assert job["result"]["tile_count"]==4
    assert len(job["result"]["features"])==1
    assert client.get(f"/projects/{project}/workspace").json()["total"]==0


def test_disk_backed_semantic_segmentation_merges_classes_across_tiles(
        monkeypatch,tmp_path):
    import json
    from vision.tiled import semantic_segmentation_tiled
    models=tmp_path/"models"
    models.mkdir()
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR",str(models))
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE","cpu")
    (models/"demo.onnx").write_bytes(b"test-provider-mocked")
    (models/"demo.json").write_text(json.dumps({
        "classes":["background","building"],"bands":[1,2,3],
        "tile_size":128,"input_scale":100,"mean":[0,0,0],"std":[1,1,1],
    }),encoding="utf-8")
    path=tmp_path/"larger.tif"
    with rasterio.open(path,"w",driver="GTiff",width=256,height=128,
                       count=3,dtype="uint16",crs="EPSG:4326",
                       transform=AFFINE) as dst:
        dst.write(np.full((3,128,256),100,dtype=np.uint16))
    calls=[]
    def fake(tile,config,device):
        calls.append((tile.shape,device))
        return (np.ones((128,128),dtype=np.uint8),
                np.full((128,128),.9,dtype=np.float32))
    monkeypatch.setattr("vision.semantic._predict_tile",fake)
    result=semantic_segmentation_tiled(
        path,"image","demo",.5,max_pixels=40000,memory_mb=8)
    assert len(calls)==2
    assert all(c==(1,3,128,128) and device=="cpu" for c,device in calls)
    assert result["classified_pixels"]==32768
    assert result["tile_count"]==2
    assert len(result["features"])==1
    assert result["features"][0]["properties"]["class_name"]=="building"
    assert result["features"][0]["properties"]["pixel_count"]==32768
    assert result["confidence_calibrated"] is False
    assert result["mean_model_confidence"]==pytest.approx(.9)


def test_diagonal_regions_are_separate_valid_polygon_features(tmp_path):
    from vision.tiled import _disk_features
    from vision.geoai import _vector_features
    from shapely.geometry import shape
    mask=np.zeros((4,4),dtype=np.uint8)
    mask[1,1]=1
    mask[2,2]=1
    path=tmp_path/"diagonal-mask.tif"
    with rasterio.open(path,"w",driver="GTiff",width=4,height=4,count=1,
                       dtype="uint8",crs="EPSG:4326",
                       transform=AFFINE,nodata=0) as dst:
        dst.write(mask,1)
    features,truncated=_disk_features(path,{1:"test"},min_pixels=1)
    assert truncated is False
    assert len(features)==2
    assert all(shape(f["geometry"]).is_valid for f in features)
    assert sum(f["properties"]["pixel_count"] for f in features)==2
    direct,limited=_vector_features(mask,AFFINE,"EPSG:4326",
                                    {1:"test"},minimum_pixels=1)
    assert len(direct)==2 and not limited


def test_tiled_scratch_quota_is_enforced_and_temp_files_cleaned(monkeypatch,tmp_path):
    path=raster(tmp_path,"scratch.tif",changed=True)
    scratch=tmp_path/"scratch";scratch.mkdir()
    monkeypatch.setenv("GEOFATHOM_RASTER_TEMP_DIR",str(scratch))
    monkeypatch.setenv("GEOFATHOM_RASTER_SCRATCH_MB","8")
    with pytest.raises(RasterError,match="quota"):
        spectral_index_tiled(path,"x","ndvi",4,1,.3,
                             tile_size=64,memory_mb=8)
    monkeypatch.setenv("GEOFATHOM_RASTER_SCRATCH_MB","16")
    with pytest.raises(RuntimeError,match="abort"):
        spectral_index_tiled(path,"x","ndvi",4,1,.3,
                             tile_size=64,memory_mb=8,
                             progress=lambda x: (_ for _ in ()).throw(
                                 RuntimeError("abort")) if x>.1 else None)
    assert list(scratch.iterdir())==[]


def test_operator_raster_limits_and_disk_admission_fail_closed(monkeypatch, tmp_path):
    """Reject invalid budgets before allocation or temporary-file creation."""
    from types import SimpleNamespace
    from vision import tiled
    monkeypatch.setenv("GEOFATHOM_RASTER_MAX_PIXELS", "invalid")
    with pytest.raises(RasterError, match="Invalid raster maximum"):
        TilePlan(64, 64, tile_size=64, max_pixels=4096, memory_mb=8)
    monkeypatch.setenv("GEOFATHOM_RASTER_MAX_PIXELS", "0")
    with pytest.raises(RasterError, match="outside the allowed range"):
        TilePlan(64, 64, tile_size=64, max_pixels=4096, memory_mb=8)
    monkeypatch.setenv("GEOFATHOM_RASTER_MAX_PIXELS", "4096")
    plan = TilePlan(64, 64, tile_size=64, max_pixels=4096, memory_mb=8)
    assert plan.count == 1
    monkeypatch.setenv("GEOFATHOM_RASTER_TEMP_DIR", str(tmp_path))
    monkeypatch.setenv("GEOFATHOM_RASTER_SCRATCH_MB", "unlimited")
    with pytest.raises(RasterError, match="Invalid raster scratch quota"):
        with tiled._scratch(plan, "rejected-"):
            pytest.fail("Invalid disk quota was accepted.")
    monkeypatch.setenv("GEOFATHOM_RASTER_SCRATCH_MB", "15")
    with pytest.raises(RasterError, match="between 16 and 2048"):
        with tiled._scratch(plan, "rejected-"):
            pytest.fail("Undersized disk quota was accepted.")
    monkeypatch.setenv("GEOFATHOM_RASTER_SCRATCH_MB", "16")
    monkeypatch.setattr(tiled.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(RasterError, match="Insufficient free disk space"):
        with tiled._scratch(plan, "rejected-"):
            pytest.fail("Insufficient disk space was accepted.")
    assert not list(tmp_path.glob("rejected-*"))
    mask = tmp_path / "mask.bin"
    mask.write_bytes(b"0123456789")
    with pytest.raises(RasterError, match="temporary-disk quota"):
        tiled._check_scratch(mask, 9)
    tiled._check_scratch(mask, 10)


def test_disk_mask_preflight_and_top_k_polygonization(monkeypatch, tmp_path):
    """Reject fragmented masks and preserve the largest real connected polygon."""
    from vision import tiled
    path = tmp_path / "categories.tif"
    labels = np.zeros((128, 128), np.uint8)
    labels[10:30, 10:30] = 1
    labels[50:60, 50:60] = 1
    with rasterio.open(path, "w", driver="GTiff", width=128, height=128,
                       count=1, dtype="uint8", nodata=0, crs="EPSG:4326",
                       transform=AFFINE) as target:
        target.write(labels, 1)
    features, truncated = tiled._disk_features(path, {1: "site"},
                                                max_features=1, min_pixels=1)
    assert truncated is True
    assert len(features) == 1
    assert features[0]["properties"]["pixel_count"] == 400
    ignored, was_truncated = tiled._disk_features(path, {2: "absent"},
                                                   max_features=1, min_pixels=1)
    assert ignored == [] and was_truncated is False
    def fail_measurement(_):
        raise ValueError("Invalid geodesy")
    monkeypatch.setattr(tiled, "measure_geometry", fail_measurement)
    with pytest.raises(RasterError, match="cannot be geodesically measured"):
        tiled._disk_features(path, {1: "site"}, max_features=1, min_pixels=1)
    monkeypatch.setattr(tiled, "_transitions",
                        lambda _: tiled.MAX_BOUNDARY_TRANSITIONS + 1)
    with rasterio.open(path) as src:
        with pytest.raises(RasterError, match="too fragmented"):
            tiled._preflight_mask(src, progress=None)


@pytest.mark.parametrize("index,first,second,threshold", [
    ("invalid", 1, 2, .2), ("ndvi", 1, 1, .2),
    ("ndvi", 1, 2, 1.), ("ndvi", 1, 5, .2),
])
def test_tiled_spectral_input_validation(tmp_path, index, first, second, threshold):
    path = raster(tmp_path, "invalid-input.tif")
    with pytest.raises(RasterError):
        spectral_index_tiled(path, "scene", index, first, second, threshold)


def test_tiled_semantic_admission_prevents_invalid_device_and_memory(monkeypatch, tmp_path):
    """No ONNX allocation is allowed before device and tensor budgets are checked."""
    from vision import tiled, semantic
    path = raster(tmp_path, "semantic-input.tif")
    config = {"bands": [1, 2, 3, 4], "classes": [f"class-{n}" for n in range(32)],
              "tile_size": 128, "max_batch": 1, "halo": 0,
              "input_scale": 100., "mean": [0.] * 4, "std": [1.] * 4}
    monkeypatch.setattr(semantic, "_manifest", lambda _: config)
    for confidence in (-.1, 1.1, float("nan")):
        with pytest.raises(RasterError, match="Confidence threshold"):
            tiled.semantic_segmentation_tiled(path, "scene", "demo", confidence)
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE", "unknown")
    with pytest.raises(RasterError, match="cpu or cuda"):
        tiled.semantic_segmentation_tiled(path, "scene", "demo", memory_mb=4)
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE", "cpu")
    with pytest.raises(RasterError, match="output tensors exceed"):
        tiled.semantic_segmentation_tiled(path, "scene", "demo", memory_mb=4)
