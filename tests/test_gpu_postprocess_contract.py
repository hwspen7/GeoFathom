"""Verify GPU dispatch borrows OrtValue output instead of copying logits."""
import numpy as np
from vision import semantic,device_postprocess

def test_cuda_postprocess_passes_resident_output(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE_POSTPROCESS","1")
    monkeypatch.setenv("GEOFATHOM_CUDA_DEVICE_ID","0")
    path=tmp_path/"model.onnx";path.write_bytes(b"mock-only")
    result=np.ones((1,128,128),np.uint8);confidence=np.ones((1,128,128),np.float32)
    marker=object()
    class Bound:
        def bind_cpu_input(self,*args):pass
        def bind_output(self,*args):assert args==("out","cuda",0)
        def synchronize_outputs(self):pass
        def get_outputs(self):return [marker]
        def copy_outputs_to_cpu(self):raise AssertionError("Logits must remain on device.")
    class Fake:
        def get_inputs(self):return [type("Input",(),{"name":"in"})()]
        def get_outputs(self):return [type("Output",(),{"name":"out"})()]
        def io_binding(self):return Bound()
        def run_with_iobinding(self,binding):pass
    monkeypatch.setattr(semantic,"_session",lambda *args:Fake())
    def decode(value,batch,classes,size,device):
        assert value is marker and (batch,classes,size,device)==(1,2,128,0)
        return result,confidence
    monkeypatch.setattr(device_postprocess,"decode_cuda_logits",decode)
    labels,scores=semantic._predict_batch(np.zeros((1,3,128,128),np.float32),
        {"model_path":path,"tile_size":128,"classes":["background","target"]},"cuda")
    assert labels is result and scores is confidence
