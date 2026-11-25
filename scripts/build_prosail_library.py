"""Generate a sensor-response-weighted physical LAI library using external PROSAIL 2.0.5.

Run in a compatible scientific Python environment with numpy and prosail==2.0.5.
No implicit sensor bands, parameter priors or atmospheric correction are assumed.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import numpy as np

ROLES=('blue','green','red','nir')
WAVELENGTH=np.arange(400.,2501.)
# Conservative explicit input envelope for this interface; not universal vegetation priors.
BOUNDS={'n':(.8,3),'cab':(0,100),'car':(0,30),'cbrown':(0,1),'cw':(.0001,.1),'cm':(.0001,.05),
        'lai':(0,12),'lidfa':(0,90),'hspot':(.001,1),'tts':(0,80),'tto':(0,80),'psi':(0,360),'rsoil':(0,2),'psoil':(0,1),'ant':(0,40)}

def response_weights(response):
    x=np.asarray(response,dtype=float)
    if x.ndim!=2 or x.shape[1]!=2 or len(x)<2 or len(x)>10000 or not np.isfinite(x).all():
        raise ValueError('Each response needs ordered finite wavelength,response pairs.')
    w,r=x.T
    if w[0]<400 or w[-1]>2500 or np.any(np.diff(w)<=0) or np.any(r<0) or r[0]!=0 or r[-1]!=0:
        raise ValueError('Responses must be nonnegative, ordered within 400–2500 nm, and zero at both support endpoints.')
    # Integrate on the combined native simulator and measured response knots,
    # preserving narrow response support instead of rounding to band centers.
    axis=np.unique(np.r_[w,WAVELENGTH[(WAVELENGTH>=w[0])&(WAVELENGTH<=w[-1])]])
    weights=np.interp(axis,w,r);area=np.trapezoid(weights,axis)
    if not np.isfinite(area) or area<=0:raise ValueError('Nonzero finite response integral required.')
    return axis,weights/area

def simulate(config,model,joint=False):
    if set(config)!={'sensor','responses','samples'} or not isinstance(config['sensor'],str) or not config['sensor'].strip():
        raise ValueError('Provide explicit sensor, response curves and parameter samples.')
    if set(config['responses'])!=set(ROLES):raise ValueError('Provide blue, green, red and NIR sensor-response curves.')
    responses=[response_weights(config['responses'][r]) for r in ROLES]
    samples=config['samples']
    if not 2<=len(samples)<=2048:raise ValueError('Supply 2–2048 explicit parameter/prior samples.')
    out=[]
    for sample in samples:
        if set(sample)!=set(BOUNDS)|{'prior'}:raise ValueError('Every PROSAIL parameter and prior mass must be specified.')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in sample.values()):
            raise ValueError('All parameter values must be finite real numbers.')
        for name,(lo,hi) in BOUNDS.items():
            if not lo<=sample[name]<=hi:raise ValueError('Parameter outside supported envelope: '+name)
        if sample['prior']<=0:raise ValueError('Prior mass must be positive.')
        args={k:sample[k] for k in BOUNDS}
        spectrum=np.asarray(model(**args,prospect_version='D',typelidf=2,factor='SDR'),float)
        if spectrum.shape!=WAVELENGTH.shape or not np.isfinite(spectrum).all() or np.any(spectrum< -1e-8):
            raise ValueError('Invalid PROSAIL directional reflectance spectrum.')
        values=[float(np.trapezoid(np.interp(axis,WAVELENGTH,spectrum)*weights,axis)) for axis,weights in responses]
        if not all(0<=x<=1 for x in values):raise ValueError('Band-integrated spectrum outside library reflectance range [0,1].')
        out.append([sample['lai'],*([sample['cab']] if joint else []),sample['prior'],*values])
    if len({row[0] for row in out})<2:raise ValueError('Library requires at least two distinct LAI values.')
    if joint and len({row[1] for row in out})<2:raise ValueError('Joint library requires at least two distinct Cab values.')
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('config',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--joint',action='store_true')
    args=parser.parse_args()
    if importlib.metadata.version('prosail')!='2.0.5':raise RuntimeError('Use the explicitly supported prosail==2.0.5 engine.')
    import prosail
    raw=args.config.read_bytes();config=json.loads(raw);rows=simulate(config,prosail.run_prosail,joint=args.joint)
    receipt=args.output.with_suffix(args.output.suffix+'.json')
    if args.output.exists() or receipt.exists():raise FileExistsError('Choose new output and receipt paths.')
    with args.output.open('x',newline='',encoding='utf-8') as stream:csv.writer(stream).writerows(rows)
    receipt.write_text(json.dumps({'engine':'prosail 2.0.5','model':'PROSPECT-D + 4SAIL SDR','sensor':config['sensor'],
        'config_sha256':hashlib.sha256(raw).hexdigest(),'library_csv_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
        'samples':len(rows),'columns':['lai',*(['cab'] if args.joint else []),'prior',*ROLES],'scope':'Conditional forward simulation, no empirical validation.'},indent=2),encoding='utf-8')
    return 0
if __name__=='__main__':raise SystemExit(main())
