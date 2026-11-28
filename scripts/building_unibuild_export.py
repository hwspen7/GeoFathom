"""Export a permitted full UniBuild checkpoint to GeoFathom's ONNX contract.

ONNX output is a candidate only; it requires separate CUDA and full-image
qualification. Never modify the installed baseline or upstream repository.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from imagery.store import file_sha256
from vision.building_external import upstream_identity,source_rgb
from vision.building_dataset import canonical_sha
from scripts.building_external_predict import safe_load,unibuild_model


def parity(expected,actual):
    if (expected.shape!=actual.shape or expected.shape!=(1,1,512,512)
            or not np.isfinite(expected).all() or not np.isfinite(actual).all()
            or np.any((expected<0)|(expected>1)) or np.any((actual<0)|(actual>1))):
        raise ValueError("Invalid UniBuild export head.")
    error=float(np.max(np.abs(expected-actual)))
    disagreement=float(np.mean((expected>=.5)!=(actual>=.5)))
    if error>.002 or disagreement>.001:
        raise ValueError("UniBuild PyTorch/ONNX parity failed.")
    return {"maximum_probability_error":error,"mask_disagreement_fraction":disagreement,"passed":True}


def export(root,checkpoint,sample,output,authorized):
    import torch
    import onnx
    import onnxruntime as ort
    root=Path(root).resolve();checkpoint=Path(checkpoint).resolve()
    sample=Path(sample).resolve();output=Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a fresh ONNX output directory.")
    identity=upstream_identity("unibuild",root,checkpoint,authorized=authorized)
    rgb=source_rgb(sample);size=512
    inputs=[]
    for y,x in sorted({(0,0),(max(0,rgb.shape[0]-size),max(0,rgb.shape[1]-size))}):
        patch=np.zeros((size,size,3),np.float32)
        crop=rgb[y:y+size,x:x+size];patch[:crop.shape[0],:crop.shape[1]]=crop/255.
        normalized=(patch-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
        inputs.append(torch.from_numpy(normalized.transpose(2,0,1).copy())[None])
    safe_load(torch)
    torch.set_num_threads(4);torch.manual_seed(731)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(root));cwd=Path.cwd();os.chdir(root)
    try:
        model=unibuild_model(checkpoint,"cpu")
        class Head(torch.nn.Module):
            def __init__(self,m):
                super().__init__();self.model=m
            def forward(self,x):
                out=self.model(x)
                logits=out["logits"] if isinstance(out,dict) else out
                logits=torch.nn.functional.interpolate(logits,size=(512,512),mode="bilinear",align_corners=False)
                return torch.softmax(logits.float(),dim=1)[:,1:2]
        head=Head(model).eval()
        output.parent.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(prefix=".unibuild-export-",dir=output.parent) as temp:
            stage=Path(temp)/"result";stage.mkdir();weights=stage/"model.onnx"
            torch.onnx.export(head,inputs[0],str(weights),opset_version=17,input_names=["image"],
                              output_names=["probability"],dynamo=False)
            onnx.checker.check_model(str(weights))
            graph=onnx.load(str(weights),load_external_data=False)
            if any(t.data_location==onnx.TensorProto.EXTERNAL for t in graph.graph.initializer):
                raise ValueError("GeoFathom requires a self-contained ONNX graph.")
            options=ort.SessionOptions();options.intra_op_num_threads=4
            ort.disable_telemetry_events()
            session=ort.InferenceSession(str(weights),sess_options=options,providers=["CPUExecutionProvider"])
            checks=[]
            with torch.inference_mode():
                for inp in inputs:
                    checks.append(parity(head(inp).numpy(),session.run(None,{"image":inp.numpy()})[0]))
            if upstream_identity("unibuild",root,checkpoint,authorized=authorized)!=identity:
                raise ValueError("Upstream checkpoint changed during export.")
            config={"task":"building_extraction","classes":["background","building"],"bands":[1,2,3],
                    "tile_size":512,"halo":64,"max_batch":1,"input_scale":255.,
                    "mean":[.485,.456,.406],"std":[.229,.224,.225],"output_type":"binary_probability",
                    "output_channels":1,"output_channel":0,"description":"UniBuild HR-DPT local ONNX candidate",
                    "weights_sha256":file_sha256(weights),"upstream":identity}
            (stage/"model.json").write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
            report={"model_sha256":config["weights_sha256"],"manifest_sha256":file_sha256(stage/"model.json"),
                    "sample_sha256":file_sha256(sample),"checks":checks,"upstream":identity,
                    "qualification":"cpu_tile_parity_only",
                    "note":"Native upstream overlap blending differs from GeoFathom halo-core tiling. Run full-image comparisons again."}
            report["sha256"]=canonical_sha(report)
            (stage/"export.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
            stage.replace(output)
    finally:
        os.chdir(cwd);sys.path.remove(str(root))
    print(json.dumps(report,indent=2))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path,required=True)
    p.add_argument("--sample",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--authorized",action="store_true")
    a=p.parse_args();export(a.upstream,a.checkpoint,a.sample,a.output,a.authorized)
