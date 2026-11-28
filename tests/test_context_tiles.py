"""Coverage, edge alignment and seam rejection with context-aware inference."""
import numpy as np
import pytest
from vision.tiles import context_tiles

@pytest.mark.parametrize("width,height,halo",[(1,1,0),(257,139,16),(512,512,32),(128,256,0),(9,145,31)])
def test_context_cores_cover_every_pixel_once(width,height,halo):
    output=np.zeros((height,width),np.uint8)
    for t in context_tiles(width,height,128,halo):
        x,y=int(t.core.col_off),int(t.core.row_off)
        w,h=int(t.core.width),int(t.core.height)
        output[y:y+h,x:x+w]+=1
        assert t.input_col+int(t.read.width)<=128
        assert t.input_row+int(t.read.height)<=128
        assert t.crop[0].stop-t.crop[0].start==h
        assert t.crop[1].stop-t.crop[1].start==w
        assert int(t.read.col_off)-t.input_col+halo==x
        assert int(t.read.row_off)-t.input_row+halo==y
    assert np.all(output==1)

def test_invalid_context():
    with pytest.raises(ValueError):
        list(context_tiles(128,128,128,64))

def test_streamed_inference_discards_artificial_tile_edge_predictions(tmp_path,monkeypatch):
    import json
    import rasterio
    from rasterio.transform import from_origin
    from vision.tiled import semantic_segmentation_tiled
    root=tmp_path/"models";root.mkdir()
    (root/"demo.onnx").write_bytes(b"mock")
    (root/"demo.json").write_text(json.dumps({
        "classes":["background","object"],"bands":[1,2,3],
        "tile_size":128,"halo":16,"input_scale":100}))
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR",str(root))
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE","cpu")
    scene=tmp_path/"scene.tif"
    with rasterio.open(scene,"w",driver="GTiff",width=203,height=117,
            count=3,dtype="uint8",crs="EPSG:4326",
            transform=from_origin(10,30,.00001,.00001)) as ds:
        ds.write(np.full((3,117,203),100,np.uint8))
    def predict(tensor,config,device):
        labels=np.ones((128,128),np.uint8)
        labels[:16]=0;labels[-16:]=0;labels[:,:16]=0;labels[:,-16:]=0
        return labels,np.ones_like(labels,dtype=np.float32)
    monkeypatch.setattr("vision.semantic._predict_tile",predict)
    result=semantic_segmentation_tiled(scene,"test","demo",memory_mb=8)
    assert result["classified_pixels"]==203*117
    assert result["tile_count"]==6
    assert result["context_halo"]==16
    assert len(result["features"])==1


@pytest.mark.parametrize("window", [(11, 17, 110, 91), (95, 96, 100, 60), (0, 0, 257, 139), (256, 138, 1, 1)])
def test_window_tiles_match_full_scene_context_and_cover_once(window):
    from vision.tiles import context_tiles_for_window
    left, top, width, height = window
    coverage = np.zeros((height, width), np.uint8)
    full = list(context_tiles(257, 139, 128, 16))
    for tile in context_tiles_for_window(257, 139, 128, 16, *window):
        x, y, w, h = map(int, (tile.core.col_off, tile.core.row_off, tile.core.width, tile.core.height))
        coverage[y:y+h, x:x+w] += 1
        match = next(t for t in full if t.core.col_off <= x+left < t.core.col_off+t.core.width
                     and t.core.row_off <= y+top < t.core.row_off+t.core.height)
        assert tile.read == match.read
        assert (tile.input_row, tile.input_col) == (match.input_row, match.input_col)
        assert tile.crop[0].start == match.crop[0].start+y+top-match.core.row_off
        assert tile.crop[1].start == match.crop[1].start+x+left-match.core.col_off
    assert np.all(coverage == 1)
