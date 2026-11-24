"""Independent classified-LAS benchmark; real-scene validation is opt-in.

Use a locally acquired classified USGS 3DEP LAS/LAZ crop in a metre CRS.
Do not use reference labels to train the classifier. Unknown classes are
excluded and unsupported predictions are reported separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from analysis.lidar_registration import progressive_morphology
from analysis.lidar_geometry import ground_filter
from analysis.lidar_disk import _laspy,_metadata,_points,_digest
from analysis.lidar_science import metric_crs

def benchmark(path,epsg,size,radius,threshold,bbox):
    laspy=_laspy();metric_crs(epsg)
    parts=[];labels=[];count=0
    with open(path,"rb") as stream:
        digest=_digest(stream)
        with laspy.open(stream,closefd=False) as reader:
            metadata=_metadata(reader.header,epsg)
            for record in reader.chunk_iterator(100000):
                p=_points(record)
                use=(p[:,0]>=bbox[0])&(p[:,1]>=bbox[1])&(p[:,0]<bbox[2])&(p[:,1]<bbox[3])
                count+=int(use.sum())
                if count>100000:raise ValueError("Choose a smaller study area (100,000-point limit).")
                parts.append(p[use]);labels.append(np.asarray(record.classification)[use])
    if count==0:raise ValueError("No points in study area.")
    p=np.concatenate(parts);cls=np.concatenate(labels)
    truth=np.isin(cls,[2,3,4,5,6])
    if not truth.any() or not np.any(cls==2) or not np.any(np.isin(cls,[3,4,5,6])):
        raise ValueError("Study area needs both classified ground and vegetation/building reference labels.")
    report={"source_sha256":digest,"metadata":metadata,"epsg":epsg,"bounds":bbox,"points":count,
        "reference":"existing LAS class 2 versus 3–6; not independently surveyed ground truth",
        "parameters":{"size":size,"radius":radius,"threshold":threshold},"methods":{}}
    for name,fn in (("local_slope",ground_filter),("progressive_morphology",progressive_morphology)):
        out,info=fn(p,size,radius,threshold)
        supported=np.isfinite(out[:,-1]);valid=truth&supported
        pred=out[:,-1]==1;ground=cls==2
        tp=int((valid&pred&ground).sum());tn=int((valid&~pred&~ground).sum())
        fp=int((valid&pred&~ground).sum());fnn=int((valid&~pred&ground).sum())
        def ratio(a,b):return a/b if b else None
        report["methods"][name]={"tp":tp,"tn":tn,"fp":fp,"fn":fnn,
            "coverage":ratio(int(valid.sum()),int(truth.sum())),"precision":ratio(tp,tp+fp),
            "recall":ratio(tp,tp+fnn),"f1":ratio(2*tp,2*tp+fp+fnn),"accuracy_on_supported":ratio(tp+tn,tp+tn+fp+fnn),
            "unsupported_reference_points":int((truth&~supported).sum()),"algorithm_metrics":info}
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("file",type=Path);parser.add_argument("--epsg",type=int,required=True)
    parser.add_argument("--bbox",type=float,nargs=4,required=True)
    parser.add_argument("--size",type=float,default=1.);parser.add_argument("--radius",type=float,default=8.)
    parser.add_argument("--threshold",type=float,default=.3);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not args.bbox[0]<args.bbox[2] or not args.bbox[1]<args.bbox[3]:parser.error("Invalid bbox.")
    result=benchmark(args.file,args.epsg,args.size,args.radius,args.threshold,args.bbox)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf8")
    print(json.dumps(result,indent=2,allow_nan=False))
